# Issue #70 Content Source Hooks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the materializer hook, cache, capability, and replay-evidence surfaces needed for future public-domain and TTS content sources without enabling downloads or host TTS generation yet.

**Architecture:** Extract Phase-A source resolution behind a small provider registry while keeping the existing lavfi recipes as the only registered production providers. Add a content-addressed cache helper that future file-backed providers can use, expose registered provider availability through `capabilities`, and carry source-resolution evidence in `materialization.json` plus materialize/run replay bundles. Do not add public-domain or TTS scenario enum values in this change; those values should land only with working providers.

**Tech Stack:** Python 3.13, Pydantic v2, Typer, pytest, ruff, ty, existing FFmpeg/ffprobe tooling. No new dependencies.

---

## Source Inputs

**GitHub issue:** [#70 Track public-domain and TTS content source hooks](https://github.com/randomparity/chaos-librarian/issues/70)

Issue #70 asks for the hook shape, cache policy, capability reporting, and replay evidence before sources that depend on downloads or host TTS tooling are added.

**Design pointers:**

- `docs/specs/chaos-librarian-design.md:50-60` says deterministic replay comes first and content sources are pluggable.
- `docs/specs/chaos-librarian-design.md:581-630` lists current deterministic sources and later public-domain/TTS sources.
- `docs/specs/chaos-librarian-design.md:727-779` places content sources before containerization and routes tool availability through `capabilities`.
- `docs/specs/chaos-librarian-design.md:987-1001` names Sprint 10 extended profiles and the public-domain/TTS hook deliverable.
- `docs/specs/chaos-librarian-design.md:1015-1016` keeps requiring TTS and public-domain downloads out of V1.

**Execution branch:** Create or switch to `feat/issue-70-content-source-hooks` before editing code. Do not implement on `main` or `master`.

## Design Decisions Baked Into This Plan

1. This change adds hooks and evidence, not external content. It must not download media, invoke host TTS, or add public-domain/TTS values to `VideoSource`, `AudioSource`, or `SubtitleSource`.
2. Built-in lavfi recipes become registered providers so the new path is exercised by existing materialize, run, and replay flows.
3. Provider registry keys are strings, not enum-specific types, so future enum additions can register providers without reshaping the registry.
4. Cache policy is content-addressed and atomic. Cache keys and stored bytes are sha256-bound; writes stage to a sibling temp file and `Path.replace` into place.
5. `capabilities` reports registered providers. The first production provider is `builtin-lavfi`; later public-domain/TTS providers add their own entries.
6. Replay evidence is materializer-owned. Plan-only bundles do not resolve or cache media sources and therefore do not carry content-source evidence.
7. Contract schema versions bump because `capabilities`, `materialization`, and materialize/run replay bundle shapes change.
8. Source evidence records recipe identity and cache/content facts, but not machine-local absolute input paths.
9. Provider availability must be derived from the same tool probes as the
   materializer gate. A provider that requires `ffmpeg` is unavailable when the
   probed `ffmpeg` status fails.
10. Run replay comparison must include normalized source evidence from both
    `replay.json` and `materialization.json`; otherwise the new evidence can
    drift without tripping exit 6.
11. Source support validation belongs to the provider registry, not the FFmpeg
    command builder. Once a provider returns an `FFmpegInput`, the builder
    should validate only muxing concerns such as container, codec, resolution,
    and input shape.

## File Structure

### Create

```text
src/chaos_librarian/contract/content_sources.py
  Public Pydantic models for source evidence, provider capabilities, track kind,
  and cache disposition.

src/chaos_librarian/materializer/content_cache.py
  Content-addressed cache root resolution, probe, lookup, and atomic store helpers.

src/chaos_librarian/materializer/content_sources.py
  Provider protocol, source request/result dataclasses, built-in lavfi providers,
  source registry, and capability collection.

tests/contract/test_content_sources.py
tests/materializer/test_content_cache.py
tests/materializer/test_content_sources.py
```

### Modify

```text
src/chaos_librarian/contract/__init__.py
  Bump REPLAY_BUNDLE_SCHEMA_VERSION, MATERIALIZATION_SCHEMA_VERSION, and
  CAPABILITIES_SCHEMA_VERSION.

src/chaos_librarian/contract/capabilities.py
  Add content-source provider capability models to the top-level payload.

src/chaos_librarian/contract/materialization.py
  Add content_sources evidence to MaterializationReport.

src/chaos_librarian/contract/replay_bundle.py
  Add content_sources evidence to MaterializeReplayBundle only.

src/chaos_librarian/materializer/tooling/capabilities.py
  Include registered content-source capabilities in detect_capabilities().

src/chaos_librarian/materializer/tooling/ffmpeg.py
src/chaos_librarian/materializer/tooling/recipes.py
  Support FFmpegInput.file_path as a real input path, preserving lavfi behavior.

src/chaos_librarian/materializer/preflight.py
src/chaos_librarian/materializer/synthesis.py
src/chaos_librarian/materializer/run.py
src/chaos_librarian/materializer/wall_clock.py
src/chaos_librarian/materializer/replay.py
src/chaos_librarian/materializer/persistence/finalize.py
src/chaos_librarian/materializer/persistence/reports.py
  Resolve sources through the registry and thread evidence into reports/bundles.

src/chaos_librarian/engine/diff.py
  Compare normalized source evidence during run replay divergence checks.

src/chaos_librarian/cli/commands/capabilities.py
  Render provider capability details in human output.

tests/contract/test_contract_constants.py
tests/contract/test_capabilities.py
tests/contract/test_canonicalize.py
tests/contract/test_materialization.py
tests/contract/test_replay_bundle.py
tests/materializer/test_ffmpeg_builder.py
tests/materializer/test_finalize.py
tests/materializer/test_replay.py
tests/materializer/test_wall_clock.py
tests/materializer/test_capabilities.py
tests/materializer/test_writer.py
tests/cli/test_inspect.py
tests/cli/test_capabilities.py
tests/cli/test_materialize.py
tests/cli/test_replay.py
tests/cli/test_run.py
tests/integration/test_wall_clock_run.py
schemas/*.schema.json
docs/contract/schema-reference.md
docs/specs/chaos-librarian-design.md
```

## Task 1: Add Content-Source Contract Models

**Files:**
- Create: `src/chaos_librarian/contract/content_sources.py`
- Modify: `src/chaos_librarian/contract/capabilities.py`
- Modify: `src/chaos_librarian/contract/materialization.py`
- Modify: `src/chaos_librarian/contract/replay_bundle.py`
- Modify: `src/chaos_librarian/contract/__init__.py`
- Test: `tests/contract/test_content_sources.py`
- Test: `tests/contract/test_capabilities.py`
- Test: `tests/contract/test_materialization.py`
- Test: `tests/contract/test_replay_bundle.py`
- Test: `tests/contract/test_contract_constants.py`

- [ ] **Step 1: Write failing tests for the new content-source models**

Create `tests/contract/test_content_sources.py`:

```python
"""Contract tests for content-source capability and evidence models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from chaos_librarian.contract.content_sources import (
    CacheDisposition,
    ContentSourceEvidence,
    ContentSourceProviderCapability,
    ContentTrackKind,
)


def test_content_source_evidence_round_trips_builtin_video() -> None:
    evidence = ContentSourceEvidence(
        asset_id="asset_main",
        track_kind=ContentTrackKind.VIDEO,
        track_index=None,
        source="color_bars",
        provider="builtin-lavfi",
        recipe_digest="sha256:" + "0" * 64,
        cache_disposition=CacheDisposition.NOT_CACHEABLE,
        cache_key=None,
        content_hash=None,
        origin_uri=None,
        license=None,
    )

    loaded = ContentSourceEvidence.model_validate_json(evidence.model_dump_json())

    assert loaded == evidence


def test_content_source_evidence_round_trips_cached_audio() -> None:
    evidence = ContentSourceEvidence(
        asset_id="asset_main",
        track_kind="audio",
        track_index=0,
        source="future_tts",
        provider="example-tts",
        recipe_digest="sha256:" + "1" * 64,
        cache_disposition="miss_stored",
        cache_key="sha256:" + "2" * 64,
        content_hash="sha256:" + "3" * 64,
        origin_uri="tts:example:voice-a",
        license="generated-test-fixture",
    )

    loaded = ContentSourceEvidence.model_validate_json(evidence.model_dump_json())

    assert loaded.track_kind is ContentTrackKind.AUDIO
    assert loaded.cache_disposition is CacheDisposition.MISS_STORED


def test_content_source_evidence_rejects_bad_recipe_digest() -> None:
    payload = {
        "asset_id": "asset_main",
        "track_kind": "video",
        "source": "color_bars",
        "provider": "builtin-lavfi",
        "recipe_digest": "not-a-digest",
        "cache_disposition": "not_cacheable",
    }

    with pytest.raises(ValidationError):
        ContentSourceEvidence.model_validate(payload)


def test_content_source_provider_capability_round_trips() -> None:
    capability = ContentSourceProviderCapability(
        name="builtin-lavfi",
        available=True,
        requires_network=False,
        requires_cache=False,
        required_tool="ffmpeg",
        cache_dir=None,
        cache_writable=None,
        reason=None,
        sources=(
            "audio:channel_tones",
            "audio:silence",
            "audio:sine",
            "video:color_bars",
            "video:mandelbrot",
            "video:solid_color",
        ),
    )

    loaded = ContentSourceProviderCapability.model_validate_json(
        capability.model_dump_json()
    )

    assert loaded == capability
```

- [ ] **Step 2: Add failing tests for embedding the models in public contracts**

In `tests/contract/test_capabilities.py`, update `_ok_tool`-based construction to include content-source capabilities:

```python
from chaos_librarian.contract.content_sources import (
    ContentSourceCapabilities,
    ContentSourceProviderCapability,
)


def _content_source_caps() -> ContentSourceCapabilities:
    return ContentSourceCapabilities(
        providers=[
            ContentSourceProviderCapability(
                name="builtin-lavfi",
                available=True,
                requires_network=False,
                requires_cache=False,
                required_tool="ffmpeg",
                sources=("video:color_bars",),
            )
        ]
    )
```

Use `content_sources=_content_source_caps()` in every `Capabilities(...)` payload and assert:

```python
assert loaded.content_sources.providers[0].name == "builtin-lavfi"
```

In `tests/contract/test_materialization.py`, add content-source evidence to `_minimal_report` defaults:

```python
from chaos_librarian.contract.content_sources import ContentSourceEvidence


def _source_evidence() -> ContentSourceEvidence:
    return ContentSourceEvidence(
        asset_id="a0",
        track_kind="video",
        source="color_bars",
        provider="builtin-lavfi",
        recipe_digest="sha256:" + "0" * 64,
        cache_disposition="not_cacheable",
    )
```

Set `"content_sources": [_source_evidence()]` in `_minimal_report()` and add:

```python
def test_materialization_report_carries_content_source_evidence() -> None:
    report = _minimal_report()
    assert report.content_sources[0].provider == "builtin-lavfi"
```

In `tests/contract/test_replay_bundle.py`, add `content_sources` to `_materialize_base()` and `_materialize_payload()`:

```python
"content_sources": [
    {
        "asset_id": "asset_main",
        "track_kind": "video",
        "source": "color_bars",
        "provider": "builtin-lavfi",
        "recipe_digest": "sha256:" + "0" * 64,
        "cache_disposition": "not_cacheable",
    }
],
```

Then add:

```python
def test_materialize_bundle_carries_content_source_evidence():
    bundle = MaterializeReplayBundle.model_validate(_materialize_payload())
    assert bundle.content_sources[0].source == "color_bars"
```

- [ ] **Step 3: Verify tests fail before implementation**

Run:

```bash
uv run pytest tests/contract/test_content_sources.py \
  tests/contract/test_capabilities.py \
  tests/contract/test_materialization.py \
  tests/contract/test_replay_bundle.py -q
```

Expected: import failures for `chaos_librarian.contract.content_sources` and validation failures for missing fields.

- [ ] **Step 4: Add `contract/content_sources.py`**

Create `src/chaos_librarian/contract/content_sources.py`:

```python
"""Content-source capability and replay-evidence contract models."""

from __future__ import annotations

import enum

from pydantic import BaseModel, ConfigDict, Field

SHA256_URI_PATTERN = r"^sha256:[0-9a-f]{64}$"


class ContentTrackKind(enum.StrEnum):
    """Track family a content source resolved."""

    VIDEO = "video"
    AUDIO = "audio"
    SUBTITLE = "subtitle"


class CacheDisposition(enum.StrEnum):
    """How a provider used the content-source cache for one resolution."""

    NOT_CACHEABLE = "not_cacheable"
    HIT = "hit"
    MISS_STORED = "miss_stored"


class ContentSourceEvidence(BaseModel):
    """Replay evidence for one resolved content source."""

    model_config = ConfigDict(extra="forbid")

    asset_id: str
    track_kind: ContentTrackKind
    source: str
    provider: str
    recipe_digest: str = Field(pattern=SHA256_URI_PATTERN)
    track_index: int | None = Field(default=None, ge=0)
    cache_disposition: CacheDisposition
    cache_key: str | None = Field(default=None, pattern=SHA256_URI_PATTERN)
    content_hash: str | None = Field(default=None, pattern=SHA256_URI_PATTERN)
    origin_uri: str | None = None
    license: str | None = None


class ContentSourceProviderCapability(BaseModel):
    """Capability report for one registered content-source provider."""

    model_config = ConfigDict(extra="forbid")

    name: str
    available: bool
    requires_network: bool
    requires_cache: bool
    required_tool: str | None = None
    cache_dir: str | None = None
    cache_writable: bool | None = None
    reason: str | None = None
    sources: tuple[str, ...] = Field(default_factory=tuple)


class ContentSourceCapabilities(BaseModel):
    """All registered content-source providers visible to capabilities."""

    model_config = ConfigDict(extra="forbid")

    providers: list[ContentSourceProviderCapability] = Field(default_factory=list)
```

- [ ] **Step 5: Embed content-source models in capabilities, reports, and replay bundles**

Modify `src/chaos_librarian/contract/capabilities.py`:

```python
from chaos_librarian.contract.content_sources import ContentSourceCapabilities
```

Add to `Capabilities`:

```python
    content_sources: ContentSourceCapabilities
```

Modify `src/chaos_librarian/contract/materialization.py`:

```python
from chaos_librarian.contract.content_sources import ContentSourceEvidence
```

Add to `MaterializationReport`:

```python
    content_sources: list[ContentSourceEvidence]
```

Modify `src/chaos_librarian/contract/replay_bundle.py`:

```python
from chaos_librarian.contract.content_sources import ContentSourceEvidence
```

Add only to `MaterializeReplayBundle`:

```python
    content_sources: list[ContentSourceEvidence]
```

- [ ] **Step 6: Bump schema versions and constants tests**

Modify `src/chaos_librarian/contract/__init__.py`:

```python
REPLAY_BUNDLE_SCHEMA_VERSION: Final = 6
MATERIALIZATION_SCHEMA_VERSION: Final = 7
CAPABILITIES_SCHEMA_VERSION: Final = 2
```

Update `tests/contract/test_contract_constants.py` to assert the same values.
Update hardcoded `schema_version` values in the tests touched by this task.

- [ ] **Step 7: Run contract tests for this task**

Run:

```bash
uv run pytest tests/contract/test_content_sources.py \
  tests/contract/test_capabilities.py \
  tests/contract/test_canonicalize.py \
  tests/contract/test_materialization.py \
  tests/contract/test_replay_bundle.py \
  tests/contract/test_contract_constants.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/chaos_librarian/contract tests/contract
git commit -m "feat(contract): add content source evidence models"
```

## Task 2: Add Cache Policy Primitives

**Files:**
- Create: `src/chaos_librarian/materializer/content_cache.py`
- Test: `tests/materializer/test_content_cache.py`

- [ ] **Step 1: Write failing cache tests**

Create `tests/materializer/test_content_cache.py`:

```python
"""Tests for content-source cache policy primitives."""

from __future__ import annotations

from pathlib import Path

import pytest

from chaos_librarian.materializer.content_cache import (
    ContentCache,
    cache_key_for_bytes,
    cache_key_for_path,
    default_content_cache_root,
    probe_content_cache,
)


def test_cache_key_for_bytes_is_sha256_uri() -> None:
    assert (
        cache_key_for_bytes(b"abc")
        == "sha256:ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )


def test_cache_key_for_path_streams_file_digest(tmp_path: Path) -> None:
    path = tmp_path / "clip.bin"
    path.write_bytes(b"abc")

    assert cache_key_for_path(path) == cache_key_for_bytes(b"abc")


def test_store_bytes_writes_content_addressed_path(tmp_path: Path) -> None:
    cache = ContentCache(tmp_path)
    key = cache_key_for_bytes(b"payload")

    record = cache.store_bytes(cache_key=key, content=b"payload")

    assert record.cache_key == key
    assert record.content_hash == key
    assert record.path == cache.path_for(cache_key=key)
    assert record.path.read_bytes() == b"payload"


def test_store_file_writes_content_addressed_path(tmp_path: Path) -> None:
    cache = ContentCache(tmp_path / "cache")
    source = tmp_path / "source.bin"
    source.write_bytes(b"payload")
    key = cache_key_for_path(source)

    record = cache.store_file(cache_key=key, source_path=source)

    assert record.cache_key == key
    assert record.content_hash == key
    assert record.path.read_bytes() == b"payload"


def test_lookup_returns_none_for_missing_key(tmp_path: Path) -> None:
    cache = ContentCache(tmp_path)
    key = cache_key_for_bytes(b"missing")

    assert cache.lookup(cache_key=key) is None


def test_lookup_returns_existing_record(tmp_path: Path) -> None:
    cache = ContentCache(tmp_path)
    key = cache_key_for_bytes(b"payload")
    cache.store_bytes(cache_key=key, content=b"payload")

    record = cache.lookup(cache_key=key)

    assert record is not None
    assert record.cache_key == key
    assert record.content_hash == key
    assert record.path.read_bytes() == b"payload"


def test_lookup_rejects_corrupt_cached_bytes(tmp_path: Path) -> None:
    cache = ContentCache(tmp_path)
    key = cache_key_for_bytes(b"payload")
    path = cache.path_for(cache_key=key)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"tampered")

    with pytest.raises(ValueError, match="cached content hash mismatch"):
        cache.lookup(cache_key=key)


def test_store_bytes_rejects_digest_mismatch(tmp_path: Path) -> None:
    cache = ContentCache(tmp_path)
    key = cache_key_for_bytes(b"expected")

    with pytest.raises(ValueError, match="content hash mismatch"):
        cache.store_bytes(cache_key=key, content=b"actual")


def test_path_for_rejects_non_sha256_uri(tmp_path: Path) -> None:
    cache = ContentCache(tmp_path)

    with pytest.raises(ValueError, match="sha256"):
        cache.path_for(cache_key="../escape")


def test_probe_content_cache_reports_writable_existing_root(tmp_path: Path) -> None:
    probe = probe_content_cache(tmp_path)

    assert probe.root == tmp_path
    assert probe.writable is True
    assert probe.reason is None


def test_default_cache_root_honors_env_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    custom = tmp_path / "cache"
    monkeypatch.setenv("CHAOS_LIBRARIAN_CONTENT_CACHE", str(custom))

    assert default_content_cache_root() == custom
```

- [ ] **Step 2: Verify tests fail before implementation**

Run:

```bash
uv run pytest tests/materializer/test_content_cache.py -q
```

Expected: import failure for `chaos_librarian.materializer.content_cache`.

- [ ] **Step 3: Implement the cache helper**

Create `src/chaos_librarian/materializer/content_cache.py`:

```python
"""Content-addressed cache primitives for future file-backed content sources."""

from __future__ import annotations

import hashlib
import os
import platform
import shutil
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Final

_CACHE_ENV: Final = "CHAOS_LIBRARIAN_CONTENT_CACHE"
_SHA256_PREFIX: Final = "sha256:"


@dataclass(frozen=True, slots=True)
class CacheProbe:
    """Non-mutating cache-root probe result for capabilities output."""

    root: Path
    writable: bool
    reason: str | None


@dataclass(frozen=True, slots=True)
class CacheRecord:
    """Stored cache artifact evidence."""

    cache_key: str
    content_hash: str
    path: Path


def cache_key_for_bytes(content: bytes) -> str:
    """Return the sha256 URI used as both cache key and content hash."""
    return _SHA256_PREFIX + hashlib.sha256(content).hexdigest()


def cache_key_for_path(path: Path) -> str:
    """Return the sha256 URI for ``path`` using a streaming file digest."""
    with path.open("rb") as fh:
        return _SHA256_PREFIX + hashlib.file_digest(fh, "sha256").hexdigest()


def default_content_cache_root() -> Path:
    """Return the default content-source cache root without creating it."""
    override = os.environ.get(_CACHE_ENV)
    if override:
        return Path(override).expanduser()
    system = platform.system().lower()
    if system == "darwin":
        return Path.home() / "Library" / "Caches" / "chaos-librarian" / "content-sources"
    if system == "windows":
        local = os.environ.get("LOCALAPPDATA")
        base = Path(local) if local else Path.home() / "AppData" / "Local"
        return base / "chaos-librarian" / "Cache" / "content-sources"
    xdg = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg) if xdg else Path.home() / ".cache"
    return base / "chaos-librarian" / "content-sources"


def probe_content_cache(root: Path | None = None) -> CacheProbe:
    """Report whether the cache root or its parent appears writable."""
    resolved = root if root is not None else default_content_cache_root()
    probe_target = resolved if resolved.exists() else resolved.parent
    if not probe_target.exists():
        return CacheProbe(root=resolved, writable=False, reason="parent_missing")
    if not os.access(probe_target, os.W_OK):
        return CacheProbe(root=resolved, writable=False, reason="not_writable")
    return CacheProbe(root=resolved, writable=True, reason=None)


class ContentCache:
    """Content-addressed cache rooted at a caller-selected directory."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root if root is not None else default_content_cache_root()

    def path_for(self, *, cache_key: str) -> Path:
        """Map a sha256 URI cache key to a contained cache path."""
        digest = _digest_from_cache_key(cache_key)
        return self.root / digest[:2] / digest[2:4] / digest

    def lookup(self, *, cache_key: str) -> CacheRecord | None:
        """Return a stored record for ``cache_key`` or None when absent."""
        path = self.path_for(cache_key=cache_key)
        if not path.exists():
            return None
        content_hash = cache_key_for_path(path)
        if content_hash != cache_key:
            raise ValueError(
                f"cached content hash mismatch for cache key {cache_key}: "
                f"got {content_hash}"
            )
        return CacheRecord(cache_key=cache_key, content_hash=content_hash, path=path)

    def store_bytes(self, *, cache_key: str, content: bytes) -> CacheRecord:
        """Atomically store bytes under ``cache_key`` after digest verification."""
        content_hash = cache_key_for_bytes(content)
        if content_hash != cache_key:
            raise ValueError(
                f"content hash mismatch for cache key {cache_key}: got {content_hash}"
            )
        path = self.path_for(cache_key=cache_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as fh:
            temp_path = Path(fh.name)
            fh.write(content)
        temp_path.replace(path)
        return CacheRecord(cache_key=cache_key, content_hash=content_hash, path=path)

    def store_file(self, *, cache_key: str, source_path: Path) -> CacheRecord:
        """Atomically copy ``source_path`` into cache after digest verification."""
        content_hash = cache_key_for_path(source_path)
        if content_hash != cache_key:
            raise ValueError(
                f"content hash mismatch for cache key {cache_key}: got {content_hash}"
            )
        path = self.path_for(cache_key=cache_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        with source_path.open("rb") as src:
            with NamedTemporaryFile(
                dir=path.parent, prefix=f".{path.name}.", delete=False
            ) as dst:
                temp_path = Path(dst.name)
                shutil.copyfileobj(src, dst)
        temp_path.replace(path)
        return CacheRecord(cache_key=cache_key, content_hash=content_hash, path=path)


def _digest_from_cache_key(cache_key: str) -> str:
    if not cache_key.startswith(_SHA256_PREFIX):
        raise ValueError(f"cache key must start with {_SHA256_PREFIX!r}: {cache_key!r}")
    digest = cache_key.removeprefix(_SHA256_PREFIX)
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise ValueError(f"cache key must be a lowercase sha256 URI: {cache_key!r}")
    return digest
```

- [ ] **Step 4: Run cache tests**

Run:

```bash
uv run pytest tests/materializer/test_content_cache.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/chaos_librarian/materializer/content_cache.py \
  tests/materializer/test_content_cache.py
git commit -m "feat(materializer): add content source cache primitive"
```

## Task 3: Add Provider Registry And Preserve Built-In Source Behavior

**Files:**
- Create: `src/chaos_librarian/materializer/content_sources.py`
- Modify: `src/chaos_librarian/materializer/tooling/recipes.py`
- Modify: `src/chaos_librarian/materializer/tooling/ffmpeg.py`
- Modify: `src/chaos_librarian/materializer/preflight.py`
- Test: `tests/materializer/test_content_sources.py`
- Test: `tests/materializer/test_ffmpeg_builder.py`

- [ ] **Step 1: Write failing tests for file-backed FFmpeg inputs**

Add to `tests/materializer/test_ffmpeg_builder.py`:

```python
from chaos_librarian.materializer.tooling.recipes import FFmpegInput


def test_file_backed_video_input_uses_file_path(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"not-real-media")
    output = tmp_path / "asset.mkv"

    argv = build_command(
        video=_video(),
        video_input=FFmpegInput(file_path=source),
        audios=[_audio()],
        audio_inputs=[recipe_sine(channels="stereo", duration_s=1.0, seed=1)],
        output_path=output,
    )

    assert "-f" not in argv[: argv.index("-i")]
    assert str(source) in argv


def test_build_command_does_not_own_source_support_after_resolution(
    tmp_path: Path,
) -> None:
    """Source support belongs to providers; build_command muxes resolved inputs."""
    video = VideoTrack(source=VideoSource.NOISE, codec="h264", resolution="hd")
    output = tmp_path / "asset.mkv"

    argv = build_command(
        video=video,
        video_input=recipe_color_bars(width=1280, height=720, fps=24, duration_s=1.0, seed=1),
        audios=[_audio()],
        audio_inputs=[recipe_sine(channels="stereo", duration_s=1.0, seed=1)],
        output_path=output,
    )

    assert str(output) in argv


def test_ffmpeg_input_rejects_missing_input() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        FFmpegInput()


def test_ffmpeg_input_rejects_two_inputs(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="exactly one"):
        FFmpegInput(lavfi="color=s=1x1", file_path=tmp_path / "source.mp4")
```

- [ ] **Step 2: Write failing tests for built-in provider resolution**

Create `tests/materializer/test_content_sources.py`:

```python
"""Tests for content-source provider registry."""

from __future__ import annotations

import pytest

from chaos_librarian.contract.content_sources import CacheDisposition, ContentTrackKind
from chaos_librarian.contract.scenario import AudioSource, VideoSource
from chaos_librarian.materializer.content_sources import (
    SourceRequest,
    collect_content_source_capabilities,
    resolve_audio_source,
    resolve_video_source,
)
from chaos_librarian.materializer.errors import UnsupportedMaterializationError


def test_resolve_video_source_returns_input_and_evidence() -> None:
    result = resolve_video_source(
        source=VideoSource.COLOR_BARS,
        request=SourceRequest(
            asset_id="asset_main",
            track_kind=ContentTrackKind.VIDEO,
            track_index=None,
            source=VideoSource.COLOR_BARS.value,
            seed=42,
            duration_s=2.0,
            width=640,
            height=480,
            fps=24,
            channels=None,
        ),
    )

    assert result.ffmpeg_input.lavfi == "smptebars=size=640x480:rate=24"
    assert result.evidence.asset_id == "asset_main"
    assert result.evidence.provider == "builtin-lavfi"
    assert result.evidence.cache_disposition is CacheDisposition.NOT_CACHEABLE


def test_resolve_audio_source_records_track_index() -> None:
    result = resolve_audio_source(
        source=AudioSource.SINE,
        request=SourceRequest(
            asset_id="asset_main",
            track_kind=ContentTrackKind.AUDIO,
            track_index=0,
            source=AudioSource.SINE.value,
            seed=42,
            duration_s=2.0,
            width=None,
            height=None,
            fps=None,
            channels="stereo",
        ),
    )

    assert result.ffmpeg_input.lavfi is not None
    assert result.evidence.track_kind is ContentTrackKind.AUDIO
    assert result.evidence.track_index == 0


def test_unregistered_video_source_is_rejected() -> None:
    with pytest.raises(UnsupportedMaterializationError) as exc:
        resolve_video_source(
            source=VideoSource.NOISE,
            request=SourceRequest(
                asset_id="asset_main",
                track_kind=ContentTrackKind.VIDEO,
                track_index=None,
                source=VideoSource.NOISE.value,
                seed=1,
                duration_s=1.0,
                width=640,
                height=480,
                fps=24,
                channels=None,
            ),
        )

    assert exc.value.field == "video.source"


def test_collect_content_source_capabilities_reports_builtin_provider() -> None:
    caps = collect_content_source_capabilities(ffmpeg_available=True)

    assert [provider.name for provider in caps.providers] == ["builtin-lavfi"]
    assert caps.providers[0].available is True
    assert "video:color_bars" in caps.providers[0].sources


def test_collect_content_source_capabilities_marks_builtin_unavailable_without_ffmpeg() -> None:
    caps = collect_content_source_capabilities(ffmpeg_available=False)

    provider = caps.providers[0]
    assert provider.name == "builtin-lavfi"
    assert provider.available is False
    assert provider.reason == "required tool unavailable: ffmpeg"
```

- [ ] **Step 3: Verify tests fail before implementation**

Run:

```bash
uv run pytest tests/materializer/test_ffmpeg_builder.py \
  tests/materializer/test_content_sources.py -q
```

Expected: `FFmpegInput()` does not yet validate one-of fields and `content_sources` does not exist.

- [ ] **Step 4: Tighten `FFmpegInput` and support file inputs**

Modify `src/chaos_librarian/materializer/tooling/recipes.py`:

```python
@dataclass(frozen=True, slots=True)
class FFmpegInput:
    """One ffmpeg input plus per-input flags."""

    lavfi: str | None = None
    file_path: Path | None = None
    extra_flags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (self.lavfi is None) == (self.file_path is None):
            raise ValueError("FFmpegInput requires exactly one of lavfi or file_path")
```

Modify `src/chaos_librarian/materializer/tooling/ffmpeg.py`.

First, remove source allow-listing from the builder. Source support is now
owned by `content_sources.resolve_*`; `build_command()` only muxes already
resolved inputs and validates container/codec/resolution:

```python
def _validate_video(video: VideoTrack) -> None:
    """Reject video tracks outside the muxing matrix."""
    _require(video.codec, _SUPPORTED_VIDEO_CODECS, "video.codec")
    _require(video.resolution, _SUPPORTED_RESOLUTIONS, "video.resolution")
```

Delete `_SUPPORTED_VIDEO_SOURCES` and remove any `_require(video.source, ...)`
call. Replace the old `test_unsupported_video_source_rejected` builder test
with `test_build_command_does_not_own_source_support_after_resolution`; the
provider-registry test `test_unregistered_video_source_is_rejected` is now the
source-support guard.

Then replace `_video_input_args` and `_audio_input_args` with a shared helper:

```python
def _input_args(ffmpeg_input: FFmpegInput, *, field: str) -> list[str]:
    if ffmpeg_input.lavfi is not None:
        return [*ffmpeg_input.extra_flags, "-f", "lavfi", "-i", ffmpeg_input.lavfi]
    if ffmpeg_input.file_path is not None:
        return [*ffmpeg_input.extra_flags, "-i", str(ffmpeg_input.file_path)]
    raise UnsupportedMaterializationError(
        "FFmpegInput must carry lavfi or file_path",
        field=field,
        payload={},
    )


def _video_input_args(video_input: FFmpegInput) -> list[str]:
    """Argv slice for the video input."""
    return _input_args(video_input, field="video.source")


def _audio_input_args(audio_inputs: Sequence[FFmpegInput]) -> list[str]:
    """Argv slice covering all audio inputs."""
    args: list[str] = []
    for audio_input in audio_inputs:
        args.extend(_input_args(audio_input, field="audio.source"))
    return args
```

- [ ] **Step 5: Add provider registry module**

Create `src/chaos_librarian/materializer/content_sources.py`:

```python
"""Content-source provider registry used by Phase-A synthesis."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final, Protocol

from chaos_librarian.contract.content_sources import (
    CacheDisposition,
    ContentSourceCapabilities,
    ContentSourceEvidence,
    ContentSourceProviderCapability,
    ContentTrackKind,
)
from chaos_librarian.contract.scenario import AudioSource, VideoSource
from chaos_librarian.materializer.errors import UnsupportedMaterializationError
from chaos_librarian.materializer.tooling.recipes import (
    FFmpegInput,
    recipe_channel_tones,
    recipe_color_bars,
    recipe_mandelbrot,
    recipe_silence,
    recipe_sine,
    recipe_solid_color,
)

FPS_DEFAULT: Final = 24
RESOLUTION_PIXELS: Final[dict[str, tuple[int, int]]] = {
    "sd": (640, 480),
    "hd": (1280, 720),
    "1080p": (1920, 1080),
}


@dataclass(frozen=True, slots=True)
class SourceRequest:
    """Provider input for one track source resolution."""

    asset_id: str
    track_kind: ContentTrackKind
    track_index: int | None
    source: str
    seed: int
    duration_s: float
    width: int | None
    height: int | None
    fps: int | None
    channels: str | None


@dataclass(frozen=True, slots=True)
class SourceResolution:
    """Provider output for one source resolution."""

    ffmpeg_input: FFmpegInput
    evidence: ContentSourceEvidence


class ContentSourceProvider(Protocol):
    """Provider hook shape for current built-ins and future external sources."""

    provider_name: str

    def resolve(self, request: SourceRequest) -> SourceResolution:
        """Resolve a request into an ffmpeg input and replay evidence."""

    def capability(self) -> ContentSourceProviderCapability:
        """Return provider availability for capabilities output."""


Recipe = Callable[..., FFmpegInput]


class _BuiltinLavfiProvider:
    provider_name = "builtin-lavfi"

    def __init__(self, *, sources: tuple[str, ...]) -> None:
        self._sources = sources

    def capability(self) -> ContentSourceProviderCapability:
        return ContentSourceProviderCapability(
            name=self.provider_name,
            available=True,
            requires_network=False,
            requires_cache=False,
            required_tool="ffmpeg",
            sources=self._sources,
        )

    def evidence(self, request: SourceRequest) -> ContentSourceEvidence:
        return ContentSourceEvidence(
            asset_id=request.asset_id,
            track_kind=request.track_kind,
            track_index=request.track_index,
            source=request.source,
            provider=self.provider_name,
            recipe_digest=_recipe_digest(request),
            cache_disposition=CacheDisposition.NOT_CACHEABLE,
        )


class _BuiltinVideoProvider(_BuiltinLavfiProvider):
    def __init__(self, recipes: dict[VideoSource, Recipe]) -> None:
        self._recipes = recipes
        sources = tuple(f"video:{source.value}" for source in sorted(recipes, key=str))
        super().__init__(sources=sources)

    def resolve(self, request: SourceRequest) -> SourceResolution:
        source = VideoSource(request.source)
        recipe = self._recipes[source]
        if request.width is None or request.height is None or request.fps is None:
            raise ValueError("video source request requires width, height, and fps")
        ffmpeg_input = recipe(
            width=request.width,
            height=request.height,
            fps=request.fps,
            duration_s=request.duration_s,
            seed=request.seed,
        )
        return SourceResolution(ffmpeg_input=ffmpeg_input, evidence=self.evidence(request))


class _BuiltinAudioProvider(_BuiltinLavfiProvider):
    def __init__(self, recipes: dict[AudioSource, Recipe]) -> None:
        self._recipes = recipes
        sources = tuple(f"audio:{source.value}" for source in sorted(recipes, key=str))
        super().__init__(sources=sources)

    def resolve(self, request: SourceRequest) -> SourceResolution:
        source = AudioSource(request.source)
        recipe = self._recipes[source]
        if request.channels is None:
            raise ValueError("audio source request requires channels")
        ffmpeg_input = recipe(
            channels=request.channels,
            duration_s=request.duration_s,
            seed=request.seed,
        )
        return SourceResolution(ffmpeg_input=ffmpeg_input, evidence=self.evidence(request))


VIDEO_RECIPES: Final[dict[VideoSource, Recipe]] = {
    VideoSource.MANDELBROT: recipe_mandelbrot,
    VideoSource.COLOR_BARS: recipe_color_bars,
    VideoSource.SOLID_COLOR: recipe_solid_color,
}
AUDIO_RECIPES: Final[dict[AudioSource, Recipe]] = {
    AudioSource.SINE: recipe_sine,
    AudioSource.SILENCE: recipe_silence,
    AudioSource.CHANNEL_TONES: recipe_channel_tones,
}

_VIDEO_PROVIDER = _BuiltinVideoProvider(VIDEO_RECIPES)
_AUDIO_PROVIDER = _BuiltinAudioProvider(AUDIO_RECIPES)


def resolve_video_source(*, source: VideoSource, request: SourceRequest) -> SourceResolution:
    """Resolve a video source or raise the same materializer error as preflight."""
    if source not in VIDEO_RECIPES:
        raise UnsupportedMaterializationError(
            f"video source {source!r} not supported",
            field="video.source",
            payload={"supported": sorted(s.value for s in VIDEO_RECIPES)},
        )
    return _VIDEO_PROVIDER.resolve(request)


def resolve_audio_source(*, source: AudioSource, request: SourceRequest) -> SourceResolution:
    """Resolve an audio source or raise the same materializer error as preflight."""
    if source not in AUDIO_RECIPES:
        raise UnsupportedMaterializationError(
            f"audio source {source!r} not supported",
            field="audio.source",
            payload={"supported": sorted(s.value for s in AUDIO_RECIPES)},
        )
    return _AUDIO_PROVIDER.resolve(request)


def collect_content_source_capabilities(*, ffmpeg_available: bool) -> ContentSourceCapabilities:
    """Return registered content-source provider capabilities."""
    return ContentSourceCapabilities(
        providers=[
            _merge_builtin_capabilities(
                _VIDEO_PROVIDER,
                _AUDIO_PROVIDER,
                ffmpeg_available=ffmpeg_available,
            )
        ]
    )


def _merge_builtin_capabilities(
    video_provider: _BuiltinVideoProvider,
    audio_provider: _BuiltinAudioProvider,
    *,
    ffmpeg_available: bool,
) -> ContentSourceProviderCapability:
    sources = tuple(
        sorted(
            (
                *video_provider.capability().sources,
                *audio_provider.capability().sources,
            )
        )
    )
    return ContentSourceProviderCapability(
        name="builtin-lavfi",
        available=ffmpeg_available,
        requires_network=False,
        requires_cache=False,
        required_tool="ffmpeg",
        reason=None if ffmpeg_available else "required tool unavailable: ffmpeg",
        sources=sources,
    )


def _recipe_digest(request: SourceRequest) -> str:
    payload = {
        "asset_id": request.asset_id,
        "track_kind": request.track_kind.value,
        "track_index": request.track_index,
        "source": request.source,
        "seed": request.seed,
        "duration_s": request.duration_s,
        "width": request.width,
        "height": request.height,
        "fps": request.fps,
        "channels": request.channels,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()
```

- [ ] **Step 6: Update preflight to use the registry**

Modify imports in `src/chaos_librarian/materializer/preflight.py`:

```python
from chaos_librarian.contract.content_sources import ContentTrackKind
from chaos_librarian.materializer.content_sources import (
    AUDIO_RECIPES,
    FPS_DEFAULT,
    RESOLUTION_PIXELS,
    SourceRequest,
    VIDEO_RECIPES,
    resolve_audio_source,
    resolve_video_source,
)
```

Replace direct recipe calls with registry calls:

```python
    video_resolution = resolve_video_source(
        source=video.source,
        request=SourceRequest(
            asset_id="preflight",
            track_kind=ContentTrackKind.VIDEO,
            track_index=None,
            source=video.source.value,
            seed=0,
            duration_s=1.0,
            width=width,
            height=height,
            fps=FPS_DEFAULT,
            channels=None,
        ),
    )
    video_input = video_resolution.ffmpeg_input
```

In `_preflight_audio_inputs`, resolve each audio source with `track_index=index` and append `resolution.ffmpeg_input`.

- [ ] **Step 7: Run registry and FFmpeg builder tests**

Run:

```bash
uv run pytest tests/materializer/test_ffmpeg_builder.py \
  tests/materializer/test_content_sources.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/chaos_librarian/materializer/content_sources.py \
  src/chaos_librarian/materializer/tooling/recipes.py \
  src/chaos_librarian/materializer/tooling/ffmpeg.py \
  src/chaos_librarian/materializer/preflight.py \
  tests/materializer/test_content_sources.py \
  tests/materializer/test_ffmpeg_builder.py
git commit -m "feat(materializer): add content source provider registry"
```

## Task 4: Report Provider Capabilities

**Files:**
- Modify: `src/chaos_librarian/materializer/tooling/capabilities.py`
- Modify: `src/chaos_librarian/cli/commands/capabilities.py`
- Test: `tests/cli/test_capabilities.py`
- Test: `tests/contract/test_capabilities.py`
- Test: `tests/materializer/test_capabilities.py`

- [ ] **Step 1: Update capability fixtures and CLI tests**

In `tests/cli/test_capabilities.py`, import the new models:

```python
from chaos_librarian.contract.content_sources import (
    ContentSourceCapabilities,
    ContentSourceProviderCapability,
)
```

Add helper:

```python
def _content_sources() -> ContentSourceCapabilities:
    return ContentSourceCapabilities(
        providers=[
            ContentSourceProviderCapability(
                name="builtin-lavfi",
                available=True,
                requires_network=False,
                requires_cache=False,
                required_tool="ffmpeg",
                sources=("video:color_bars",),
            )
        ]
    )
```

Use `content_sources=_content_sources()` in `_caps()`.

Update every other direct `Capabilities(...)` fixture before the new required
field lands. Run:

```bash
rg -n "Capabilities\\(" tests src
```

At the time this plan was written, the test fixtures that need the same helper
or equivalent inline `content_sources` value are:

```text
tests/materializer/test_wall_clock.py
tests/materializer/test_capabilities.py
tests/materializer/test_finalize.py
tests/materializer/test_run_sprint7.py
tests/materializer/test_replay.py
tests/materializer/test_run_sprint10.py
tests/integration/test_wall_clock_run.py
tests/materializer/test_run.py
tests/cli/test_replay.py
```

Add:

```python
def test_capabilities_json_includes_content_sources(monkeypatch):
    monkeypatch.setattr(app_mod, "detect_capabilities", lambda: _caps(all_ok=True))

    result = runner.invoke(app, ["capabilities", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["content_sources"]["providers"][0]["name"] == "builtin-lavfi"


def test_capabilities_human_output_formats_content_sources(monkeypatch):
    monkeypatch.setattr(app_mod, "detect_capabilities", lambda: _caps(all_ok=True))

    result = runner.invoke(app, ["capabilities"])

    assert result.exit_code == 0
    assert "content_sources:" in result.stdout
    assert "builtin-lavfi" in result.stdout
```

- [ ] **Step 2: Verify tests fail before implementation**

Run:

```bash
uv run pytest tests/cli/test_capabilities.py tests/contract/test_capabilities.py -q
```

Expected: failures from missing `content_sources` construction in production
`detect_capabilities()`, fixture constructors, and human output.

- [ ] **Step 3: Wire provider capabilities into detection**

Modify `src/chaos_librarian/materializer/tooling/capabilities.py`:

```python
from chaos_librarian.materializer.content_sources import collect_content_source_capabilities
```

Add to `Capabilities(...)` in `detect_capabilities()`:

```python
        content_sources=collect_content_source_capabilities(ffmpeg_available=ffmpeg_ok),
```

- [ ] **Step 4: Render content-source providers in human output**

Modify `_render_capabilities_human()` in `src/chaos_librarian/cli/commands/capabilities.py`:

```python
    typer.echo("content_sources:")
    for provider in caps.content_sources.providers:
        status = "OK" if provider.available else "UNAVAILABLE"
        suffix = f" ({provider.reason})" if provider.reason else ""
        typer.echo(f"  {provider.name:<16} [{status}]{suffix}")
        typer.echo(f"    requires_network: {provider.requires_network}")
        typer.echo(f"    requires_cache:   {provider.requires_cache}")
        if provider.required_tool is not None:
            typer.echo(f"    required_tool:    {provider.required_tool}")
        if provider.cache_dir is not None:
            typer.echo(f"    cache_dir:        {provider.cache_dir}")
        if provider.cache_writable is not None:
            typer.echo(f"    cache_writable:   {provider.cache_writable}")
        if provider.sources:
            typer.echo(f"    sources:          {', '.join(provider.sources)}")
```

- [ ] **Step 5: Run capability tests**

Run:

```bash
uv run pytest tests/cli/test_capabilities.py \
  tests/contract/test_capabilities.py \
  tests/materializer/test_capabilities.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/chaos_librarian/materializer/tooling/capabilities.py \
  src/chaos_librarian/cli/commands/capabilities.py \
  tests/cli/test_capabilities.py \
  tests/contract/test_capabilities.py \
  tests/materializer/test_capabilities.py
git commit -m "feat(capabilities): report content source providers"
```

## Task 5: Wire Source Evidence Through Phase-A Synthesis

**Files:**
- Modify: `src/chaos_librarian/materializer/synthesis.py`
- Modify: `src/chaos_librarian/materializer/run.py`
- Modify: `src/chaos_librarian/materializer/wall_clock.py`
- Modify: `src/chaos_librarian/materializer/replay.py`
- Test: `tests/materializer/test_wall_clock.py`
- Test: `tests/materializer/test_replay.py`
- Test: `tests/cli/test_replay.py`
- Test: `tests/integration/test_wall_clock_run.py`

- [ ] **Step 1: Add a result dataclass for `materialize_one_asset`**

Modify `src/chaos_librarian/materializer/synthesis.py`:

```python
from dataclasses import dataclass

from chaos_librarian.contract.content_sources import ContentSourceEvidence, ContentTrackKind
from chaos_librarian.materializer.content_sources import (
    FPS_DEFAULT,
    RESOLUTION_PIXELS,
    SourceRequest,
    resolve_audio_source,
    resolve_video_source,
)
```

Add above `materialize_one_asset`:

```python
@dataclass(frozen=True, slots=True)
class MaterializeAssetResult:
    """Phase-A result for one synthesized asset."""

    invocation: ToolInvocation
    materialized_asset: MaterializedAsset
    probed: ProbedMedia
    sidecar_hashes: dict[tuple[str, str], str]
    content_sources: tuple[ContentSourceEvidence, ...]
```

Change `materialize_one_asset()` to return `MaterializeAssetResult`.

- [ ] **Step 2: Resolve sources through providers in `materialize_one_asset`**

Replace the direct `VIDEO_RECIPES` and `AUDIO_RECIPES` calls with:

```python
    video_resolution = resolve_video_source(
        source=asset.video.source,
        request=SourceRequest(
            asset_id=asset.id,
            track_kind=ContentTrackKind.VIDEO,
            track_index=None,
            source=asset.video.source.value,
            seed=seed,
            duration_s=asset.duration_seconds,
            width=width,
            height=height,
            fps=FPS_DEFAULT,
            channels=None,
        ),
    )
    video_input = video_resolution.ffmpeg_input
    content_sources: list[ContentSourceEvidence] = [video_resolution.evidence]
```

For audio:

```python
    for index, audio in enumerate(asset.audio):
        audio_resolution = resolve_audio_source(
            source=audio.source,
            request=SourceRequest(
                asset_id=asset.id,
                track_kind=ContentTrackKind.AUDIO,
                track_index=index,
                source=audio.source.value,
                seed=seed,
                duration_s=asset.duration_seconds,
                width=None,
                height=None,
                fps=None,
                channels=audio.channels.value,
            ),
        )
        audio_inputs.append(audio_resolution.ffmpeg_input)
        content_sources.append(audio_resolution.evidence)
```

Return:

```python
    return MaterializeAssetResult(
        invocation=invocation,
        materialized_asset=materialized_asset,
        probed=probed,
        sidecar_hashes=sidecar_hashes,
        content_sources=tuple(content_sources),
    )
```

- [ ] **Step 3: Update run materialize synthesis loop**

In `src/chaos_librarian/materializer/run.py`, create a list before the loop:

```python
    content_sources: list[ContentSourceEvidence] = []
```

Replace tuple unpacking with:

```python
            result = materialize_one_asset(
                asset,
                ctx.plan_artifacts.replay_bundle.resolved_seed,
                ctx.out_dir,
                ctx.caps,
                invocation_index,
                root_path=primary_root_path,
                skip_languages=skip_languages,
            )
            invocations.append(result.invocation)
            materialized.append(result.materialized_asset)
            content_sources.extend(result.content_sources)
            augment_manifest(
                ctx.plan_artifacts.current_manifest,
                asset,
                result.materialized_asset,
                result.probed,
                result.sidecar_hashes,
                skip_languages=skip_languages,
            )
```

Pass `content_sources` into failure and success finalizers.

- [ ] **Step 4: Update wall-clock and run-replay Phase-A helpers**

In `src/chaos_librarian/materializer/wall_clock.py`, add `content_sources` to `_PhaseAResult` and extend it from each `MaterializeAssetResult`. Thread `phase_a.content_sources` into `_publish_baseline()`, `_run_timed_phase()`, and every `build_report()` / `build_replay_bundle()` call.

In `src/chaos_librarian/materializer/replay.py`, change `_synthesize_phase_a()` to return a dataclass or tuple containing `invocations`, `materialized_assets`, and `content_sources`. Use that value for success and phase-B failure report/bundle construction.

Update tests that monkeypatch `materialize_one_asset` so their fake returns `MaterializeAssetResult`.

- [ ] **Step 5: Run focused materializer tests**

Run:

```bash
uv run pytest tests/materializer/test_wall_clock.py \
  tests/materializer/test_replay.py \
  tests/cli/test_replay.py \
  tests/integration/test_wall_clock_run.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/chaos_librarian/materializer/synthesis.py \
  src/chaos_librarian/materializer/run.py \
  src/chaos_librarian/materializer/wall_clock.py \
  src/chaos_librarian/materializer/replay.py \
  tests/materializer/test_wall_clock.py \
  tests/materializer/test_replay.py \
  tests/cli/test_replay.py \
  tests/integration/test_wall_clock_run.py
git commit -m "feat(materializer): collect content source evidence"
```

## Task 6: Persist Evidence In Reports And Replay Bundles

**Files:**
- Modify: `src/chaos_librarian/materializer/persistence/reports.py`
- Modify: `src/chaos_librarian/materializer/persistence/finalize.py`
- Modify: `src/chaos_librarian/materializer/replay.py`
- Modify: `src/chaos_librarian/materializer/wall_clock.py`
- Modify: `src/chaos_librarian/engine/diff.py`
- Test: `tests/materializer/test_finalize.py`
- Test: `tests/materializer/test_writer.py`
- Test: `tests/cli/test_materialize.py`
- Test: `tests/cli/test_run.py`
- Test: `tests/cli/test_replay.py`

- [ ] **Step 1: Update report and replay builder signatures**

Modify `build_report()` in `src/chaos_librarian/materializer/persistence/reports.py`:

```python
from chaos_librarian.contract.content_sources import ContentSourceEvidence
```

Add parameter:

```python
    content_sources: list[ContentSourceEvidence],
```

Pass to `MaterializationReport(...)`:

```python
        content_sources=content_sources,
```

Modify `build_replay_bundle()`:

```python
    content_sources: list[ContentSourceEvidence],
```

Pass to `MaterializeReplayBundle(...)`:

```python
        content_sources=content_sources,
```

- [ ] **Step 2: Thread evidence through finalize paths**

Modify `finalize_success()`, `finalize_failure()`, and `finalize_failure_phase_b()` in `src/chaos_librarian/materializer/persistence/finalize.py` to accept:

```python
    content_sources: list[ContentSourceEvidence],
```

Pass the list into both `build_report()` and `build_replay_bundle()`.

For pre-Phase-A failures where no source was resolved, callers pass `[]`.

- [ ] **Step 3: Update direct callers**

Use `rg -n "build_report\\(|build_replay_bundle\\(|finalize_success\\(" src tests`
and update every call site to pass `content_sources`.

Also search direct contract constructors:

```bash
rg -n "MaterializationReport\\(|MaterializeReplayBundle\\(" tests src
```

Every direct `MaterializationReport(...)` and `MaterializeReplayBundle(...)`
constructor must include the same helper evidence shape used in contract tests.
`PlanOnlyReplayBundle(...)` constructors stay unchanged because plan-only
bundles do not carry materializer-owned source evidence.

Known production call sites:

```text
src/chaos_librarian/engine/diff.py
src/chaos_librarian/materializer/persistence/finalize.py
src/chaos_librarian/materializer/replay.py
src/chaos_librarian/materializer/wall_clock.py
src/chaos_librarian/materializer/run.py
```

Known tests with direct constructors or fake finalizers:

```text
tests/contract/test_canonicalize.py
tests/materializer/test_finalize.py
tests/materializer/test_writer.py
tests/materializer/test_replay.py
tests/cli/test_inspect.py
tests/cli/test_materialize.py
tests/cli/test_replay.py
tests/cli/test_run.py
```

- [ ] **Step 4: Compare source evidence during run replay**

Add tests to `tests/cli/test_replay.py`:

```python
def _run_compare_source_evidence(recipe_digit: str = "0") -> dict[str, object]:
    return {
        "asset_id": "asset_main",
        "track_kind": "video",
        "source": "color_bars",
        "provider": "builtin-lavfi",
        "recipe_digest": "sha256:" + recipe_digit * 64,
        "cache_disposition": "not_cacheable",
    }


def test_compare_run_replay_compares_replay_content_sources(tmp_path: Path) -> None:
    left = _write_run_compare_fixture(tmp_path / "left")
    right = _write_run_compare_fixture(tmp_path / "right")
    _update_replay(
        right,
        "content_sources",
        [_run_compare_source_evidence("1")],
    )

    diff = compare_run_replay(left, right)

    assert [item.path for item in diff.files] == ["replay.json"]


def test_compare_run_replay_compares_materialization_content_sources(
    tmp_path: Path,
) -> None:
    left = _write_run_compare_fixture(tmp_path / "left")
    right = _write_run_compare_fixture(tmp_path / "right")
    _update_materialization(
        right,
        "content_sources",
        [_run_compare_source_evidence("2")],
    )

    diff = compare_run_replay(left, right)

    assert [item.path for item in diff.files] == ["materialization.json"]
```

Update `_write_run_compare_fixture()` so both generated JSON fixtures include
baseline evidence:

```python
"content_sources": [_run_compare_source_evidence()],
```

Add a replay updater beside `_update_materialization()`:

```python
def _update_replay(root: Path, field: str, value: object) -> None:
    path = root / "replay.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload[field] = value
    path.write_text(json.dumps(payload), encoding="utf-8")
```

Modify `src/chaos_librarian/engine/diff.py`:

```python
_RUN_REPLAY_COMPARE_KEYS = frozenset(
    {
        "scenario",
        "run_id",
        "resolved_seed",
        "applied_events",
        "journal_digest",
        "execution_mode",
        "content_sources",
    }
)
```

Update `_normalize_materialization_for_run_replay()`:

```python
        "content_sources": _list_or_empty(data_obj.get("content_sources")),
```

- [ ] **Step 5: Add persistence assertions**

In `tests/materializer/test_finalize.py`, assert successful finalization includes evidence in both artifacts:

```python
assert artifacts.materialization_report.content_sources[0].provider == "builtin-lavfi"
assert artifacts.replay_bundle.content_sources[0].provider == "builtin-lavfi"
```

Use a helper evidence object:

```python
def _source_evidence() -> ContentSourceEvidence:
    return ContentSourceEvidence(
        asset_id="asset_main",
        track_kind="video",
        source="color_bars",
        provider="builtin-lavfi",
        recipe_digest="sha256:" + "0" * 64,
        cache_disposition="not_cacheable",
    )
```

- [ ] **Step 6: Run focused persistence and CLI tests**

Run:

```bash
uv run pytest tests/materializer/test_finalize.py \
  tests/materializer/test_writer.py \
  tests/materializer/test_replay.py \
  tests/contract/test_canonicalize.py \
  tests/cli/test_inspect.py \
  tests/cli/test_materialize.py \
  tests/cli/test_run.py \
  tests/cli/test_replay.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/chaos_librarian/materializer/persistence/reports.py \
  src/chaos_librarian/materializer/persistence/finalize.py \
  src/chaos_librarian/materializer/replay.py \
  src/chaos_librarian/materializer/wall_clock.py \
  src/chaos_librarian/engine/diff.py \
  src/chaos_librarian/materializer/run.py \
  tests/materializer/test_finalize.py \
  tests/materializer/test_writer.py \
  tests/cli/test_materialize.py \
  tests/cli/test_run.py \
  tests/cli/test_replay.py
git commit -m "feat(replay): persist content source evidence"
```

## Task 7: Regenerate Schemas And Update Contract Docs

**Files:**
- Modify: `schemas/capabilities.schema.json`
- Modify: `schemas/materialization.schema.json`
- Modify: `schemas/replay-bundle.schema.json`
- Modify: `docs/contract/schema-reference.md`
- Modify: `docs/specs/chaos-librarian-design.md`
- Test: `tests/contract/test_schema_export.py`

- [ ] **Step 1: Regenerate schemas**

Run:

```bash
uv run python -m chaos_librarian.schema_export --write
```

Expected: schema artifacts update for capabilities, materialization, replay bundle, and shared `$defs` reached by those schemas.

- [ ] **Step 2: Update schema reference versions**

Modify `docs/contract/schema-reference.md` current version table to include:

```markdown
| replay bundle | 6 |
| materialization | 7 |
| capabilities | 2 |
```

Replace the Sprint 10 summary paragraph with:

```markdown
Scenario v7 adds explicit `profiles`, starting with `malformed-media`, and the
`corrupt_container_header` timeline action. Manifest v5 and asset-report v5
carry labeled corruption metadata on current versions/snapshots.
Replay-bundle v6, materialization v7, and capabilities v2 add content-source
provider capability and replay-evidence surfaces for future file-backed and
TTS-backed providers.
```

- [ ] **Step 3: Update design doc issue pointer**

In `docs/specs/chaos-librarian-design.md`, update the Sprint 10 deliverable bullet:

```markdown
- Public-domain / TTS content source hooks: provider registry, cache policy,
  capability reporting, and replay evidence are implemented; actual downloads
  and TTS providers remain deferred until source-specific issues.
```

Keep the V1 non-goals for requiring TTS and requiring public-domain downloads.

- [ ] **Step 4: Run schema drift and schema tests**

Run:

```bash
uv run python -m chaos_librarian.schema_export --check
uv run pytest tests/contract/test_schema_export.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add schemas docs/contract/schema-reference.md docs/specs/chaos-librarian-design.md
git commit -m "docs(contract): document content source hook schemas"
```

## Task 8: Final Verification

**Files:**
- No new edits unless verification exposes a defect.

- [ ] **Step 1: Run focused suites**

Run:

```bash
uv run pytest tests/contract/test_content_sources.py \
  tests/contract/test_capabilities.py \
  tests/contract/test_materialization.py \
  tests/contract/test_replay_bundle.py \
  tests/materializer/test_content_cache.py \
  tests/materializer/test_content_sources.py \
  tests/materializer/test_capabilities.py \
  tests/materializer/test_ffmpeg_builder.py \
  tests/materializer/test_finalize.py \
  tests/materializer/test_run.py \
  tests/materializer/test_run_sprint7.py \
  tests/materializer/test_run_sprint10.py \
  tests/materializer/test_replay.py \
  tests/materializer/test_wall_clock.py \
  tests/cli/test_capabilities.py \
  tests/cli/test_inspect.py \
  tests/cli/test_materialize.py \
  tests/cli/test_replay.py \
  tests/cli/test_run.py -q
```

Expected: PASS.

- [ ] **Step 2: Run schema drift gate**

Run:

```bash
uv run python -m chaos_librarian.schema_export --check
```

Expected: no output except success exit code 0.

- [ ] **Step 3: Run lint, format check, and type check**

Run:

```bash
uv run ruff check .
uv run ruff format --check .
uv run ty check src tests
```

Expected: all commands exit 0 with no warnings.

- [ ] **Step 4: Review own diff**

Run:

```bash
git diff --stat main...HEAD
git diff main...HEAD -- src/chaos_librarian/contract src/chaos_librarian/materializer tests docs schemas
```

Check:

- No public-domain or TTS scenario enum values were added.
- No network or TTS subprocess code was added.
- Every new contract field is represented in tests and regenerated schemas.
- Source evidence is present in both `materialization.json` and materialize/run `replay.json`.
- `capabilities --json` validates against `Capabilities`.

- [ ] **Step 5: Run pre-commit hooks**

Run:

```bash
prek run --all-files
```

Expected: PASS. If hooks modify files, inspect the diff and rerun the focused tests affected by those files.

- [ ] **Step 6: Commit verification fixes if needed**

If Step 1-5 required fixes:

```bash
git add <changed-files>
git commit -m "fix: finish content source hook verification"
```

If no fixes were needed, do not create an empty commit.

## Self-Review Checklist

- Spec coverage: issue #70's hook shape is Task 3, cache policy is Task 2, capability reporting is Task 4, and replay evidence is Tasks 5-7.
- Scope control: the plan intentionally excludes downloads, host TTS invocation, and new public-domain/TTS scenario enum values.
- Contract coverage: capability, materialization, and materialize/run replay bundle schema versions are bumped and regenerated.
- Test coverage: contract tests cover schema models; materializer tests cover cache, provider resolution, FFmpeg input support, and evidence propagation; CLI tests cover `capabilities`.
- Readiness scan: no unresolved markers or unspecified "add tests" steps remain.
