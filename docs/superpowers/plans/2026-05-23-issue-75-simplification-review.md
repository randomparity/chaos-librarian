# Issue 75 Simplification Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Address the concrete low-risk simplification findings from the `main..HEAD` review on `feat/gh-issue-75`.

**Architecture:** Keep the Sprint 10 contract behavior unchanged while removing duplicated helper logic and reducing call-site ordering risk. Shared phase-B content helpers own SHA-256 URI formatting and suffix-preserving temp names; Phase B stamps merged version evidence once with the same oracle-over-corruption-over-media precedence.

**Tech Stack:** Python 3.13, Pydantic v2 contracts, Typer CLI, pytest, ruff, ty.

---

### Task 1: Shared Phase-B Content Helpers

**Files:**
- Create: `src/chaos_librarian/materializer/phase_b/content.py`
- Modify: `src/chaos_librarian/materializer/phase_b/corruption.py`
- Modify: `src/chaos_librarian/materializer/phase_b/corruption_bytes.py`
- Modify: `src/chaos_librarian/materializer/phase_b/filesystem.py`
- Modify: `src/chaos_librarian/materializer/phase_b/media.py`
- Modify: `src/chaos_librarian/materializer/phase_b/oracle_hash.py`
- Test: `tests/materializer/test_phase_b_content.py`

- [ ] **Step 1: Write the failing helper tests**

```python
from __future__ import annotations

import hashlib
from pathlib import Path

from chaos_librarian.materializer.phase_b.content import (
    hash_bytes,
    hash_file,
    temp_sibling,
)


def test_hash_bytes_returns_sha256_uri() -> None:
    assert hash_bytes(b"abc") == "sha256:" + hashlib.sha256(b"abc").hexdigest()


def test_hash_file_returns_sha256_uri(tmp_path: Path) -> None:
    path = tmp_path / "asset.mkv"
    path.write_bytes(b"abc")

    assert hash_file(path) == "sha256:" + hashlib.sha256(b"abc").hexdigest()


def test_temp_sibling_keeps_media_suffix_at_the_end(tmp_path: Path) -> None:
    output = tmp_path / "asset.mkv"

    assert temp_sibling(output, 42) == tmp_path / "asset.tmp.42.mkv"
```

- [ ] **Step 2: Run helper tests to verify they fail**

Run: `uv run pytest tests/materializer/test_phase_b_content.py -q`

Expected: FAIL because `chaos_librarian.materializer.phase_b.content` does not exist.

- [ ] **Step 3: Add the shared helper**

```python
"""Shared phase-B content helpers."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Final

_SHA256_PREFIX: Final = "sha256:"


def hash_bytes(data: bytes) -> str:
    """Return ``sha256:<hex>`` for ``data``."""
    return _SHA256_PREFIX + hashlib.sha256(data).hexdigest()


def hash_file(path: Path) -> str:
    """Return ``sha256:<hex>`` for the file at ``path`` without full-file allocation."""
    with path.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    return _SHA256_PREFIX + digest


def temp_sibling(output_path: Path, resolved_seed: int) -> Path:
    """Return a same-directory temp path that preserves the final suffix."""
    if output_path.suffix:
        return output_path.with_name(f"{output_path.stem}.tmp.{resolved_seed}{output_path.suffix}")
    return output_path.with_name(f"{output_path.name}.tmp.{resolved_seed}")
```

- [ ] **Step 4: Replace duplicated helpers**

Import `hash_bytes`, `hash_file`, and `temp_sibling` from `phase_b.content` where needed. Remove private copies from `media.py`, `oracle_hash.py`, and `corruption_bytes.py`. Use `hash_file` for `touch_mtime` and `wrong_oracle_hash` so those paths stream instead of `read_bytes()`.

- [ ] **Step 5: Run focused tests**

Run: `uv run pytest tests/materializer/test_phase_b_content.py tests/materializer/test_corruption.py tests/materializer/test_filesystem.py tests/materializer/test_oracle_hash.py tests/materializer/test_media.py -q`

Expected: PASS.

### Task 2: Corruption Action Builder Reuse

**Files:**
- Modify: `src/chaos_librarian/materializer/phase_b/corruption.py`
- Test: `tests/materializer/test_corruption.py`

- [ ] **Step 1: Run existing corruption characterization tests**

Run: `uv run pytest tests/materializer/test_corruption.py -q`

Expected: PASS before the refactor.

- [ ] **Step 2: Route header corruption through `_corruption_action`**

Replace the manual `CorruptionAction(...)` construction in `_apply_corrupt_container_header` with:

```python
return _corruption_action(
    entry=entry,
    action=TimelineActionName.CORRUPT_CONTAINER_HEADER,
    finalized=finalized,
    started=started,
    corruptor=_state_delta_str(delta, "corruptor"),
    byte_start=byte_start,
    byte_count=byte_count,
    seed_material=seed_material,
)
```

- [ ] **Step 3: Run corruption tests**

Run: `uv run pytest tests/materializer/test_corruption.py -q`

Expected: PASS.

### Task 3: Merge Phase-B Version Evidence Once

**Files:**
- Modify: `src/chaos_librarian/materializer/phase_b/__init__.py`
- Test: `tests/materializer/test_phase_b.py`

- [ ] **Step 1: Write failing precedence/call-count test**

Add this test near `test_augment_phase_b_outputs_stamps_all_phase_b_evidence`:

```python
def test_augment_phase_b_outputs_merges_version_evidence_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(tmp_path)
    state.media_ctx.post_phase_b_versions["version_shared"] = (HASH_A, None)
    state.corruption_ctx.post_phase_b_versions["version_shared"] = (HASH_B, None)
    state.oracle_hash_ctx.post_phase_b_oracle_hashes["version_shared"] = (HASH_C, None)
    calls: list[dict[str, tuple[str, ProbedMedia | None]]] = []

    def capture_versions(
        _manifest: Manifest,
        versions: dict[str, tuple[str, ProbedMedia | None]],
    ) -> None:
        calls.append(dict(versions))

    monkeypatch.setattr(phase_b, "augment_versions", capture_versions)

    phase_b.augment_phase_b_outputs(_manifest_with_version("version_shared"), state)

    assert calls == [{"version_shared": (HASH_C, None)}]
```

Add this helper:

```python
def _manifest_with_version(version_id: str) -> Manifest:
    return Manifest(
        schema_version=6,
        works=[],
        variants=[],
        bundles=[],
        assets=[],
        versions=[ManifestVersion(id=version_id, asset_id="asset_main", index=1)],
        locations=[],
        sidecars=[],
    )
```

- [ ] **Step 2: Run phase-B test to verify it fails**

Run: `uv run pytest tests/materializer/test_phase_b.py::test_augment_phase_b_outputs_merges_version_evidence_once -q`

Expected: FAIL because `augment_versions` is called once per version map.

- [ ] **Step 3: Merge maps before stamping**

Add a helper in `phase_b/__init__.py`:

```python
def _version_evidence(state: PhaseBState) -> dict[str, tuple[str, ProbedMedia | None]]:
    versions: dict[str, tuple[str, ProbedMedia | None]] = {}
    versions.update(state.media_ctx.post_phase_b_versions)
    versions.update(state.corruption_ctx.post_phase_b_versions)
    versions.update(state.oracle_hash_ctx.post_phase_b_oracle_hashes)
    return versions
```

Change `augment_phase_b_outputs` to call `augment_versions(manifest, _version_evidence(state))` once.

- [ ] **Step 4: Run phase-B tests**

Run: `uv run pytest tests/materializer/test_phase_b.py -q`

Expected: PASS.

### Task 4: Keyword-Only Phase-B Action Lists

**Files:**
- Modify: `src/chaos_librarian/materializer/persistence/finalize.py`
- Modify: `src/chaos_librarian/materializer/run.py`
- Modify: `tests/materializer/test_finalize.py`

- [ ] **Step 1: Write failing signature test**

Extend `test_report_and_finalize_builders_require_explicit_content_sources` with:

```python
for func in (finalize_mod.finalize_success, finalize_mod.finalize_failure_phase_b):
    for name in (
        "filesystem_actions",
        "media_actions",
        "corruption_actions",
        "oracle_hash_actions",
    ):
        assert inspect.signature(func).parameters[name].kind is inspect.Parameter.KEYWORD_ONLY
```

- [ ] **Step 2: Run signature test to verify it fails**

Run: `uv run pytest tests/materializer/test_finalize.py::test_report_and_finalize_builders_require_explicit_content_sources -q`

Expected: FAIL because the action lists are positional parameters.

- [ ] **Step 3: Make action lists keyword-only**

Move `filesystem_actions`, `media_actions`, `corruption_actions`, and `oracle_hash_actions` after `*` in `finalize_success` and `finalize_failure_phase_b`. Update `run.py` and `tests/materializer/test_finalize.py` call sites to pass those names explicitly.

- [ ] **Step 4: Run finalize and run tests**

Run: `uv run pytest tests/materializer/test_finalize.py tests/materializer/test_run.py tests/materializer/test_run_sprint10.py -q`

Expected: PASS.

### Task 5: Packet-Probe Error Boundary

**Files:**
- Modify: `src/chaos_librarian/materializer/phase_b/packet_probe.py`
- Test: `tests/materializer/test_packet_probe.py`

- [ ] **Step 1: Write failing timeout/launch-error test**

```python
def test_packet_probe_wraps_subprocess_launch_failures(monkeypatch) -> None:
    def fake_run(_argv, **_kwargs):
        raise OSError("ffprobe missing")

    monkeypatch.setattr(packet_probe, "_run_ffprobe_packets", fake_run)
    invocations: list[ToolInvocation] = []

    with pytest.raises(PacketProbeError, match="ffprobe packet probe failed"):
        resolve_packet_byte_range(
            Path("asset.mkv"),
            stream="video",
            packet_start=0,
            packet_count=1,
            invocations=invocations,
        )

    assert invocations == []
```

- [ ] **Step 2: Run packet-probe test to verify it fails**

Run: `uv run pytest tests/materializer/test_packet_probe.py::test_packet_probe_wraps_subprocess_launch_failures -q`

Expected: FAIL because `OSError` escapes directly.

- [ ] **Step 3: Wrap subprocess boundary failures**

Wrap `_run_ffprobe_packets(argv)` in `try/except (OSError, subprocess.SubprocessError)` and raise `PacketProbeError` with a clear message. Keep existing `ValueError` wrapping for nonzero exits and parse failures so invocation indexes remain unchanged after a completed ffprobe process.

- [ ] **Step 4: Run packet-probe tests**

Run: `uv run pytest tests/materializer/test_packet_probe.py tests/materializer/test_corruption.py -q`

Expected: PASS.

### Task 6: Verification And Commit

**Files:**
- Modify only files touched by Tasks 1-5 plus this plan.

- [ ] **Step 1: Run focused test suite**

Run: `uv run pytest tests/materializer/test_phase_b_content.py tests/materializer/test_corruption.py tests/materializer/test_filesystem.py tests/materializer/test_oracle_hash.py tests/materializer/test_media.py tests/materializer/test_phase_b.py tests/materializer/test_finalize.py tests/materializer/test_packet_probe.py tests/materializer/test_run.py tests/materializer/test_run_sprint10.py -q`

Expected: PASS.

- [ ] **Step 2: Run lint and format checks**

Run: `uv run ruff check . && uv run ruff format --check .`

Expected: PASS.

- [ ] **Step 3: Run type checker**

Run: `uv run ty check src tests`

Expected: PASS.

- [ ] **Step 4: Commit**

Run:

```bash
git add docs/superpowers/plans/2026-05-23-issue-75-simplification-review.md \
  src/chaos_librarian/materializer/phase_b \
  src/chaos_librarian/materializer/persistence/finalize.py \
  src/chaos_librarian/materializer/run.py \
  tests/materializer
git commit -m "refactor: simplify phase-b corruption helpers"
```
