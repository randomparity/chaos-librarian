# Issues 98-99 Observed-State Language Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Normalize absent/null versus `und` language only for audio/video probe
streams and document the observed-state sidecar export contract.

**Architecture:** Keep the behavior in `chaos_librarian.adapter.probe`, where
field-level probe differences are produced. Documentation in
`docs/contract/observed-state.md` describes exporter behavior without changing
schemas.

**Tech Stack:** Python 3.13, Pydantic v2 contract models, pytest, Markdown docs.

---

### Task 1: Probe Language Normalization

**Files:**
- Modify: `tests/adapter/test_probe.py`
- Modify: `tests/adapter/test_compare_final_state.py`
- Modify: `src/chaos_librarian/adapter/probe.py`

- [x] **Step 1: Add failing adapter tests**

Append these tests to `tests/adapter/test_probe.py`:

```python
def test_compare_probed_media_treats_audio_video_unknown_language_as_equivalent() -> None:
    expected = _media(
        streams=[
            ProbedStream(kind=StreamKind.VIDEO, codec="h264", language="und"),
            ProbedStream(kind=StreamKind.AUDIO, codec="aac", language=None),
        ]
    )
    observed = _media(
        streams=[
            ProbedStream(kind=StreamKind.VIDEO, codec="h264", language=None),
            ProbedStream(kind=StreamKind.AUDIO, codec="aac", language="und"),
        ]
    )

    assert compare_probed_media(expected, observed) == []


def test_compare_probed_media_keeps_subtitle_language_strict() -> None:
    expected = _media(
        streams=[ProbedStream(kind=StreamKind.SUBTITLE, codec="srt", language="und")]
    )
    observed = _media(
        streams=[ProbedStream(kind=StreamKind.SUBTITLE, codec="srt", language=None)]
    )

    differences = compare_probed_media(expected, observed)

    assert ("streams.0.language", "und", None) in differences


def test_compare_probed_media_reports_real_audio_video_language_mismatch() -> None:
    expected = _media(
        streams=[ProbedStream(kind=StreamKind.AUDIO, codec="aac", language="eng")]
    )
    observed = _media(
        streams=[ProbedStream(kind=StreamKind.AUDIO, codec="aac", language="spa")]
    )

    differences = compare_probed_media(expected, observed)

    assert ("streams.0.language", "eng", "spa") in differences
```

- [x] **Step 2: Add failing compare-level regression**

Update imports in `tests/adapter/test_compare_final_state.py`:

```python
from chaos_librarian.contract.manifest import ManifestSidecar, ProbedMedia, ProbedStream, StreamKind
```

Add this test after `test_probe_duration_uses_point_zero_five_second_tolerance`:

```python
def test_probe_unknown_language_equivalence_keeps_final_state_compare_clean() -> None:
    oracle_probe = ProbedMedia(
        container="mov,mp4,m4a,3gp,3g2,mj2",
        duration_seconds=60.0,
        size_bytes=12345,
        streams=[
            ProbedStream(kind=StreamKind.VIDEO, codec="h264", language="und"),
            ProbedStream(kind=StreamKind.AUDIO, codec="aac", language="und"),
        ],
    )
    observed_probe = oracle_probe.model_copy(
        update={
            "streams": [
                ProbedStream(kind=StreamKind.VIDEO, codec="h264", language=None),
                ProbedStream(kind=StreamKind.AUDIO, codec="aac", language=None),
            ]
        }
    )

    report = compare_fixture_to_observed(
        _fixture(probed=oracle_probe),
        _observed(probed=observed_probe),
    )

    assert "D_PROBE_MISMATCH" not in _codes(report)
```

- [x] **Step 3: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/adapter/test_probe.py tests/adapter/test_compare_final_state.py -q --no-cov
```

Expected: the new unknown-language tests fail because `"und"` and `None` are
currently compared exactly.

- [x] **Step 4: Implement minimal normalization**

Update `src/chaos_librarian/adapter/probe.py`:

```python
from chaos_librarian.contract.manifest import ProbedMedia, ProbedStream, StreamKind
```

Add this helper near `_compare_stream`:

```python
def _stream_values_equal(
    field_name: str,
    expected: ProbedStream,
    observed: ProbedStream,
) -> bool:
    expected_value = getattr(expected, field_name)
    observed_value = getattr(observed, field_name)
    if field_name != "language":
        return expected_value == observed_value
    if expected.kind in {StreamKind.AUDIO, StreamKind.VIDEO}:
        unknown_values = {None, "und"}
        if expected_value in unknown_values and observed_value in unknown_values:
            return True
    return expected_value == observed_value
```

Then replace the direct comparison in `_compare_stream` with:

```python
        if not _stream_values_equal(field_name, expected, observed):
            differences.append((f"streams.{index}.{field_name}", expected_value, observed_value))
```

- [x] **Step 5: Run adapter tests**

Run:

```bash
uv run pytest tests/adapter/test_probe.py tests/adapter/test_compare_final_state.py -q --no-cov
```

Expected: all selected adapter tests pass.

### Task 2: Observed-State Documentation

**Files:**
- Modify: `tests/docs/test_documentation.py`
- Modify: `docs/contract/observed-state.md`

- [x] **Step 1: Add failing docs guard**

Add this test after `test_contract_docs_do_not_preserve_known_stale_guidance` in
`tests/docs/test_documentation.py`:

```python
def test_observed_state_docs_cover_language_and_sidecar_normalization() -> None:
    observed_state = _read(DOCS / "contract" / "observed-state.md")

    required_snippets = [
        "Unknown stream language",
        "JSON `null`, omitted language, and `und` are equivalent",
        "Subtitle streams remain strict",
        "Consumers should export the facts they observed",
        "\"sidecars\"",
        "\"content_hash\"",
        "library-relative POSIX path",
    ]
    for snippet in required_snippets:
        assert snippet in observed_state
```

- [x] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest \
  tests/docs/test_documentation.py \
  -k observed_state_docs_cover_language_and_sidecar_normalization \
  -q --no-cov
```

Expected: fails because the new docs section does not exist yet.

- [x] **Step 3: Update observed-state docs**

Add a section before `## Topology` in `docs/contract/observed-state.md`:

```markdown
## Probe And Sidecar Normalization

Unknown stream language can appear differently across containers and ffprobe
snapshots. During `compare`, JSON `null`, omitted language, and `und` are
equivalent for audio and video streams. Consumers should export the facts they
observed rather than synthesizing container-specific language guesses.

Subtitle streams remain strict because subtitle language is assertion data. A
subtitle stream with missing language does not compare equal to `und`, `eng`, or
any other concrete tag.

Sidecars are nested under their owning asset and use library-relative POSIX path
values. Observed sidecars do not carry a separate language field; subtitle
sidecar language is represented by the path convention when applicable.

```json
{
  "observed_ref": "asset-1",
  "current_path": "movies/Synthetic.mkv",
  "probed": {
    "container": "matroska,webm",
    "duration_seconds": 60.0,
    "size_bytes": 12345,
    "streams": [
      {"kind": "video", "codec": "h264", "width": 1920, "height": 1080},
      {"kind": "audio", "codec": "aac", "language": "und", "channels": 2}
    ]
  },
  "sidecars": [
    {
      "observed_ref": "sidecar-1",
      "kind": "subtitle",
      "path": "asset-1.eng.srt",
      "content_hash": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    }
  ]
}
```
```

- [x] **Step 4: Run docs test**

Run:

```bash
uv run pytest \
  tests/docs/test_documentation.py \
  -k observed_state_docs_cover_language_and_sidecar_normalization \
  -q --no-cov
```

Expected: the docs guard passes.

### Task 3: Verification

**Files:**
- No direct edits.

- [x] **Step 1: Run focused tests**

Run:

```bash
uv run pytest \
  tests/adapter/test_probe.py \
  tests/adapter/test_compare_final_state.py \
  tests/docs/test_documentation.py \
  -q --no-cov
```

Expected: all selected tests pass.

- [x] **Step 2: Run quality gates**

Run:

```bash
uv run ruff check .
uv run ruff format --check .
uv run ty check src tests
```

Expected: all commands pass with zero warnings.
