# Advanced music artifacts and tag corruption (#118) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development
> task-by-task. Steps use checkbox (`- [ ]`) syntax. Write the failing test first, then
> the implementation, in every task.

**Goal:** Ship three music-library capabilities — (1) a `corrupt_tags` malformed-media
timeline action with a closed flavor enum (`null_bytes` / `malformed_frame`), (2) a CUE
sheet sidecar kind authored via the existing `create_sidecar` event, and (3) a poster
sidecar `image_format` selector (`png`/`jpeg`/`webp`). `SCENARIO_SCHEMA_VERSION` bumps
31 → 32 and `MATERIALIZATION_SCHEMA_VERSION` 16 → 17.

**Architecture:** `corrupt_tags` mirrors the existing byte corruptors end to end
(`TimelineActionName` member + `CorruptTagsEvent`, profile-gate entry, target/lifecycle
sets, engine handler emitting a `CorruptionRecord`, a `phase_b/corruption.py` handler
using two new pure byte helpers, and a widened `CorruptionAction.action` Literal). CUE is
a new `SidecarKind.CUE` woven into the `create_sidecar` model validator and the two
sidecar materialization paths (`_apply_create_sidecar`, `regenerate_sidecar`), reusing the
#181 `body` field. Poster `image_format` is a new `PosterImageFormat` enum field on
`CreateSidecarEvent` that selects the ffmpeg `-c:v` encoder; a static semantic rule keeps
the `to:` extension consistent with it. Manifest stays v10 throughout.

**Tech Stack:** Python 3.13, Pydantic v2, pytest, `uv` / `ruff` / `ty`. ffmpeg is needed
only for the poster jpeg/webp and CUE materialize integration tests (skipped in CI when
absent); validation/engine/byte-helper tests are pure Python.

**Spec:** `docs/superpowers/specs/2026-05-30-issue-118-music-artifacts-design.md`
**ADR:** `docs/adr/0011-music-artifacts-and-tag-corruption.md`

> **Naming note:** every failure reuses an existing validation code. Missing
> `malformed-media` → `E_PROFILE_REQUIRED`; unknown `target` → `E_TARGET_UNKNOWN`;
> cross-kind field misuse / `image_format` on non-poster / `image_format` +
> `media_type=video` → `E_FIELD_*` (Pydantic); poster `image_format`/`to:`-extension
> disagreement → `E_MATERIALIZE_UNSUPPORTED`; pending-slow-copy interaction →
> `E_LIFECYCLE_INVALID`.

---

## Invariants (hold at every commit)

- `uv run ruff check` && `uv run ruff format --check .` && `uv run ty check src tests`
  && `uv run python -m pytest -q` all green. **Never a red commit.**
- `uv run python -m chaos_librarian.schema_export --check` passes (regen + commit in the
  same task that changes a contract model).
- A contract model, its `schema_version` literal, the `__init__.py` constant, and the
  regenerated `schemas/*.schema.json` change together in **one** task/commit.
- CUE and poster `image_format` are **not** profile-gated; only `corrupt_tags` adds to
  `REQUIRED_PROFILES_BY_ACTION`.
- No new error code. Manifest stays v10.

---

## File map

- `src/chaos_librarian/contract/scenario.py` — `TagCorruptionFlavor`, `PosterImageFormat`,
  `SidecarKind.CUE`, `TimelineActionName.CORRUPT_TAGS`, `CorruptTagsEvent`,
  `CreateSidecarEvent.image_format` + validator, `TimelineEvent` union,
  `schema_version: Literal[32]`.
- `src/chaos_librarian/contract/__init__.py` — `SCENARIO_SCHEMA_VERSION` 32,
  `MATERIALIZATION_SCHEMA_VERSION` 17.
- `src/chaos_librarian/contract/materialization.py` — widen `CorruptionAction.action`
  Literal; `schema_version: Literal[17]`.
- `src/chaos_librarian/validation/rules/profile_opt_in.py` — `corrupt_tags` →
  `malformed-media`.
- `src/chaos_librarian/validation/rules/target_unknown.py` — `corrupt_tags` in the
  asset-target set.
- `src/chaos_librarian/validation/rules/timeline_lifecycle.py` — `corrupt_tags` in the
  mutation + slow-copy-incompatible sets.
- `src/chaos_librarian/validation/rules/create_sidecar_content.py` — poster
  `image_format`/`to:`-extension agreement check.
- `src/chaos_librarian/validation/rules/hierarchy.py` — `corrupt_tags` resolution branch
  (mirrors `corrupt_container_header`).
- `src/chaos_librarian/engine/events.py` — `_STATE_DELTA_KEYS[CORRUPT_TAGS]`,
  `_handle_corrupt_tags`, dispatch entry; `create_sidecar` state_delta gains
  `image_format`.
- `src/chaos_librarian/materializer/phase_b/corruption_bytes.py` — `zero_range`,
  `malformed_id3_header`.
- `src/chaos_librarian/materializer/phase_b/corruption.py` — `_apply_corrupt_tags`,
  `_HANDLERS`, `_CorruptionTimelineAction` Literal.
- `src/chaos_librarian/materializer/phase_b/sidecar_bytes.py` — `cue_payload`,
  `regenerate_sidecar` cue branch, `poster_ffmpeg_argv` `image_format` param.
- `src/chaos_librarian/materializer/phase_b/media.py` — `_apply_create_sidecar` cue +
  `image_format` branch, `LiveSidecar.image_format`.
- `schemas/scenario.schema.json`, `schemas/materialization.schema.json` — regenerated.
- `tests/**`, `tests/fixtures/scenarios/**`, `recipes/**` — new tests, fixtures, recipes,
  and the v31 → v32 mass re-pin.

---

## Task 1: Bump schema versions (scenario 32, materialization 17)

Do the mechanical bump first so every later task lands on v32/v17 and the drift gate is
green throughout.

**Files:**
- Modify: `src/chaos_librarian/contract/__init__.py`
- Modify: `src/chaos_librarian/contract/scenario.py:1196`
- Modify: `src/chaos_librarian/contract/materialization.py:287`
- Modify: all `tests/fixtures/scenarios/**/*.yaml` and `recipes/**/*.yaml` carrying
  `schema_version: 31`
- Modify: test `.py` files asserting `schema_version=31` / literal `31`
- Regenerate: `schemas/scenario.schema.json`, `schemas/materialization.schema.json`

- [ ] **Step 1: Bump the constants and literals**

In `contract/__init__.py`:
```python
SCENARIO_SCHEMA_VERSION: Final = 32
...
MATERIALIZATION_SCHEMA_VERSION: Final = 17
```
In `scenario.py` change `schema_version: Literal[31]` → `Literal[32]`. In
`materialization.py` change `schema_version: Literal[16]` → `Literal[17]`.

- [ ] **Step 2: Mass re-pin fixtures and recipes**

```bash
cd /Users/dave/src/chaos-librarian/.claude/worktrees/music-118
grep -rl "schema_version: 31" tests/fixtures/scenarios recipes \
  | xargs sed -i '' 's/schema_version: 31/schema_version: 32/'
```

- [ ] **Step 3: Re-pin test Python literals**

```bash
grep -rl "schema_version=31" tests | xargs sed -i '' 's/schema_version=31/schema_version=32/'
```
Then manually scan remaining literal-`31` schema assertions:
```bash
grep -rn "schema_version.*31\|materialization.*16\|schema_version=16" tests src | grep -v "schema_version: 32"
```
Fix any materialization `schema_version=16` test literals to `17` and any stray scenario
`31` to `32`. Do NOT touch unrelated numeric `31`/`16` (durations, byte counts).

- [ ] **Step 4: Regenerate schemas**

Run: `uv run python -m chaos_librarian.schema_export --write`
Expected: `scenario.schema.json` and `materialization.schema.json` change.

- [ ] **Step 5: Run guardrails**

Run: `uv run ruff check && uv run ruff format --check . && uv run ty check src tests && uv run python -m pytest -q && uv run python -m chaos_librarian.schema_export --check`
Expected: all PASS, drift gate clean.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: bump scenario v32 / materialization v17 (#118)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: `SidecarKind.CUE` + `CreateSidecarEvent` body/CUE validation

**Files:**
- Modify: `src/chaos_librarian/contract/scenario.py` (SidecarKind, model_validator)
- Test: `tests/contract/test_scenario_sidecar.py` (or the existing scenario sidecar test
  file; if none, create `tests/contract/test_create_sidecar_cue.py`)
- Regenerate: `schemas/scenario.schema.json`

- [ ] **Step 1: Write the failing test**

```python
import pytest
from chaos_librarian.contract.scenario import CreateSidecarEvent, SidecarKind


def test_cue_sidecar_accepts_body_and_forbids_language():
    event = CreateSidecarEvent.model_validate(
        {"id": "e1", "at": "0s", "target": "asset-1", "to": "Album/album.cue",
         "kind": "cue", "body": "FILE \"a.flac\" WAVE\n  TRACK 01 AUDIO"}
    )
    assert event.kind is SidecarKind.CUE
    assert event.body is not None


def test_cue_sidecar_rejects_language():
    with pytest.raises(ValueError, match="cue sidecar forbids language"):
        CreateSidecarEvent.model_validate(
            {"id": "e1", "at": "0s", "target": "asset-1", "to": "a.cue",
             "kind": "cue", "language": "en"}
        )
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run python -m pytest tests/contract/test_create_sidecar_cue.py -v`
Expected: FAIL (`cue` not a valid `SidecarKind`).

- [ ] **Step 3: Add the enum value and widen the body rule**

In `scenario.py` `SidecarKind`:
```python
class SidecarKind(enum.StrEnum):
    SUBTITLE = "subtitle"
    POSTER = "poster"
    NFO = "nfo"
    CUE = "cue"
```
In `CreateSidecarEvent._check_fields_match_kind`, replace the nfo-only body line:
```python
if self.kind not in {SidecarKind.NFO, SidecarKind.CUE} and self.body is not None:
    raise ValueError("body is only valid for nfo and cue sidecars")
```
The existing `self.kind != SidecarKind.SUBTITLE and self.language is not None` branch
already produces `"cue sidecar forbids language"` via the f-string; keep it. The
codec/source/encoding non-subtitle rejection and the `media_type` poster-only rejection
already cover cue.

- [ ] **Step 4: Run to verify pass**

Run: `uv run python -m pytest tests/contract/test_create_sidecar_cue.py -v`
Expected: PASS.

- [ ] **Step 5: Regenerate schema + guardrails**

Run: `uv run python -m chaos_librarian.schema_export --write && uv run ruff check && uv run ruff format --check . && uv run ty check src tests && uv run python -m pytest -q`
Expected: all PASS; `scenario.schema.json` gains the `cue` enum value.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: add SidecarKind.CUE with body, no language (#118)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: CUE materialization (`cue_payload` + create/update branches)

**Files:**
- Modify: `src/chaos_librarian/materializer/phase_b/sidecar_bytes.py` (`cue_payload`,
  `regenerate_sidecar` cue branch)
- Modify: `src/chaos_librarian/materializer/phase_b/media.py` (`_apply_create_sidecar`
  cue branch)
- Test: `tests/materializer/test_sidecar_bytes.py` (or create
  `tests/materializer/phase_b/test_cue_payload.py`)

- [ ] **Step 1: Write the failing test**

```python
from chaos_librarian.contract.scenario import SidecarKind
from chaos_librarian.materializer.phase_b.sidecar_bytes import cue_payload


def test_cue_payload_uses_authored_body_verbatim():
    body = "FILE \"album.flac\" WAVE\n  TRACK 01 AUDIO\n    INDEX 01 00:00:00\n"
    assert cue_payload(body=body, sidecar_id="sc-1") == body.encode("utf-8")


def test_cue_payload_default_is_deterministic_and_nonempty():
    a = cue_payload(body=None, sidecar_id="sc-1")
    b = cue_payload(body=None, sidecar_id="sc-1")
    assert a == b and a.startswith(b"FILE ") and b"TRACK 01 AUDIO" in a
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run python -m pytest tests/materializer/phase_b/test_cue_payload.py -v`
Expected: FAIL (`cue_payload` undefined).

- [ ] **Step 3: Implement `cue_payload`**

In `sidecar_bytes.py`:
```python
def cue_payload(*, body: str | None, sidecar_id: str) -> bytes:
    """Return CUE-sheet bytes: authored body verbatim, else a minimal default."""
    if body is not None:
        return body.encode("utf-8")
    return (
        f'PERFORMER "Chaos Librarian"\n'
        f'TITLE "{sidecar_id}"\n'
        f'FILE "{sidecar_id}.flac" WAVE\n'
        f"  TRACK 01 AUDIO\n"
        f'    TITLE "Track 1"\n'
        f"    INDEX 01 00:00:00\n"
    ).encode("utf-8")
```

- [ ] **Step 4: Wire create + update branches**

In `media.py` `_apply_create_sidecar`, add before the `else` fallthrough:
```python
elif kind == SidecarKind.CUE:
    temp_output.write_bytes(cue_payload(body=body_text, sidecar_id=sidecar_id))
```
(import `cue_payload`). In `sidecar_bytes.py` `regenerate_sidecar`, add a cue branch
mirroring the nfo branch so `update_sidecar` regenerates a CUE (authored body verbatim,
else default).

- [ ] **Step 5: Run to verify pass + guardrails**

Run: `uv run python -m pytest tests/materializer/phase_b/test_cue_payload.py -v && uv run ruff check && uv run ty check src tests && uv run python -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: synthesize CUE sidecar bytes on create/update (#118)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: `PosterImageFormat` + `CreateSidecarEvent.image_format` (shape validation)

**Files:**
- Modify: `src/chaos_librarian/contract/scenario.py` (`PosterImageFormat`,
  `CreateSidecarEvent.image_format`, validator)
- Test: `tests/contract/test_create_sidecar_image_format.py`
- Regenerate: `schemas/scenario.schema.json`

- [ ] **Step 1: Write the failing test**

```python
import pytest
from chaos_librarian.contract.scenario import (
    CreateSidecarEvent, PosterImageFormat, SidecarMediaType,
)


def test_poster_accepts_image_format():
    e = CreateSidecarEvent.model_validate(
        {"id": "e1", "at": "0s", "target": "a", "to": "cover.webp",
         "kind": "poster", "image_format": "webp"}
    )
    assert e.image_format is PosterImageFormat.WEBP


def test_image_format_rejected_on_nfo():
    with pytest.raises(ValueError, match="image_format is only valid for poster"):
        CreateSidecarEvent.model_validate(
            {"id": "e1", "at": "0s", "target": "a", "to": "x.nfo",
             "kind": "nfo", "image_format": "png"}
        )


def test_image_format_rejected_with_video_media_type():
    with pytest.raises(ValueError, match="image_format cannot be combined with media_type"):
        CreateSidecarEvent.model_validate(
            {"id": "e1", "at": "0s", "target": "a", "to": "cover.png",
             "kind": "poster", "image_format": "png", "media_type": "video"}
        )
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run python -m pytest tests/contract/test_create_sidecar_image_format.py -v`
Expected: FAIL (`PosterImageFormat` undefined).

- [ ] **Step 3: Add enum, field, and validator branches**

In `scenario.py` near `SidecarMediaType`:
```python
class PosterImageFormat(enum.StrEnum):
    """Image format for a poster/album-art sidecar."""

    PNG = "png"
    JPEG = "jpeg"
    WEBP = "webp"
```
Add to `CreateSidecarEvent`:
```python
    image_format: PosterImageFormat | None = None
```
In `_check_fields_match_kind`, add:
```python
if self.kind != SidecarKind.POSTER and self.image_format is not None:
    raise ValueError("image_format is only valid for poster sidecars")
if self.image_format is not None and self.media_type is SidecarMediaType.VIDEO:
    raise ValueError("image_format cannot be combined with media_type=video")
```

- [ ] **Step 4: Run to verify pass + regenerate + guardrails**

Run: `uv run python -m pytest tests/contract/test_create_sidecar_image_format.py -v && uv run python -m chaos_librarian.schema_export --write && uv run ruff check && uv run ty check src tests && uv run python -m pytest -q`
Expected: PASS; `scenario.schema.json` gains `image_format` + `PosterImageFormat`.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: add poster image_format selector (#118)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: Poster `image_format`/`to:`-extension agreement rule

**Files:**
- Modify: `src/chaos_librarian/validation/rules/create_sidecar_content.py`
- Test: `tests/validation/test_create_sidecar_content.py`
- Create: `tests/fixtures/scenarios/invalid/create-sidecar-image-format-extension-mismatch.yaml`

- [ ] **Step 1: Write the failing test**

```python
from chaos_librarian.validation.codes import E_MATERIALIZE_UNSUPPORTED
from tests.validation.support import codes_for  # existing helper; adjust import to repo


def test_image_format_must_match_to_extension(validate_raw):
    raw = {
        "id": "e1", "at": "0s", "target": "asset-1", "to": "Album/cover.png",
        "kind": "poster", "image_format": "webp",
    }
    assert E_MATERIALIZE_UNSUPPORTED in codes_for_event(raw)  # webp bytes, .png path
```
(Use the repo's existing validation-rule test harness pattern; mirror a sibling test in
`tests/validation/test_create_sidecar_content.py` for exact fixtures/helpers.)

- [ ] **Step 2: Run to verify failure**

Run: `uv run python -m pytest tests/validation/test_create_sidecar_content.py -k image_format -v`
Expected: FAIL (no rule emits the code).

- [ ] **Step 3: Implement the agreement check**

In `create_sidecar_content.py`, after the subtitle checks, for poster events with a
non-None `image_format`:
```python
_EXTENSIONS_BY_FORMAT: Final[dict[str, frozenset[str]]] = {
    "png": frozenset({"png"}),
    "jpeg": frozenset({"jpg", "jpeg"}),
    "webp": frozenset({"webp"}),
}
```
Read `image_format` and the `to` path's lowercased suffix; if the suffix is not in the
allowed set, emit `E_MATERIALIZE_UNSUPPORTED` at `("timeline", idx, "image_format")` with
a message like `f"poster image_format {fmt!r} requires a matching {to!r} extension"`.

- [ ] **Step 4: Add the invalid corpus fixture**

`tests/fixtures/scenarios/invalid/create-sidecar-image-format-extension-mismatch.yaml`
first line `# expected: E_MATERIALIZE_UNSUPPORTED`, a minimal scenario with one music
track asset and a `create_sidecar` poster event `image_format: webp` / `to: ...cover.png`.

- [ ] **Step 5: Run to verify pass + guardrails**

Run: `uv run python -m pytest tests/validation -k "image_format or invalid_corpus" -q && uv run ruff check && uv run ty check src tests && uv run python -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: validate poster image_format matches to: extension (#118)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: Poster `image_format` materialization (encoder + extension)

**Files:**
- Modify: `src/chaos_librarian/materializer/phase_b/sidecar_bytes.py`
  (`poster_ffmpeg_argv` `image_format` param)
- Modify: `src/chaos_librarian/materializer/phase_b/media.py` (`LiveSidecar.image_format`,
  thread through create + update)
- Modify: `src/chaos_librarian/engine/events.py` (`create_sidecar` state_delta +
  `_STATE_DELTA_KEYS`)
- Test: `tests/materializer/phase_b/test_poster_image_format.py`

- [ ] **Step 1: Write the failing test (argv encoder selection)**

```python
from chaos_librarian.materializer.phase_b.sidecar_bytes import poster_ffmpeg_argv
from pathlib import Path


def test_poster_argv_selects_webp_encoder():
    argv = poster_ffmpeg_argv(
        output_path=Path("cover.webp"), resolved_seed=1, sidecar_id="sc-1",
        media_type=None, image_format="webp",
    )
    assert "libwebp" in argv


def test_poster_argv_defaults_to_png():
    argv = poster_ffmpeg_argv(
        output_path=Path("cover.png"), resolved_seed=1, sidecar_id="sc-1",
        media_type=None, image_format=None,
    )
    assert "libwebp" not in argv and "mjpeg" not in argv
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run python -m pytest tests/materializer/phase_b/test_poster_image_format.py -v`
Expected: FAIL (`poster_ffmpeg_argv` has no `image_format` param).

- [ ] **Step 3: Add `image_format` to `poster_ffmpeg_argv`**

Extend the image branch to insert `-c:v` per format:
```python
_ENCODER_BY_FORMAT: Final[dict[str, str]] = {
    "png": "png", "jpeg": "mjpeg", "webp": "libwebp",
}
```
When `media_type != "video"`, append `["-c:v", _ENCODER_BY_FORMAT[image_format or "png"]]`
to the existing image argv before `str(output_path)`. `png` keeps today's bytes
(explicit `-c:v png` is the default ffmpeg picks for `.png`, so the default-path test
stays green; if byte-identity for existing png fixtures regresses, omit `-c:v` when
`image_format` is `None`).

- [ ] **Step 4: Thread through create/update/state_delta**

- `media.py` `LiveSidecar`: add `image_format: str | None = None`.
- `_apply_create_sidecar`: read `image_format = delta.get("image_format")`, pass to
  `poster_ffmpeg_argv`, store on `LiveSidecar`.
- `regenerate_sidecar`: accept + forward `image_format` to `poster_ffmpeg_argv`; caller
  in `_apply_update_sidecar` passes `live.image_format`.
- `engine/events.py` `_handle_create_sidecar` state_delta: add
  `"image_format": event.image_format.value if event.image_format is not None else None`.
- `_STATE_DELTA_KEYS[CREATE_SIDECAR]`: add `"image_format"`.

- [ ] **Step 5: Run to verify pass + guardrails**

Run: `uv run python -m pytest tests/materializer/phase_b/test_poster_image_format.py tests/engine -k "state_delta or sidecar" -q && uv run ruff check && uv run ty check src tests && uv run python -m pytest -q`
Expected: PASS (incl. `test_state_delta_keys_match_contract`).

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: synthesize poster sidecar in png/jpeg/webp (#118)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: `TagCorruptionFlavor` + `CorruptTagsEvent` + union (contract)

**Files:**
- Modify: `src/chaos_librarian/contract/scenario.py`
- Test: `tests/contract/test_corrupt_tags_event.py`
- Regenerate: `schemas/scenario.schema.json`

- [ ] **Step 1: Write the failing test**

```python
import pytest
from chaos_librarian.contract.scenario import (
    CorruptTagsEvent, TagCorruptionFlavor, TimelineActionName,
)


def test_corrupt_tags_defaults():
    e = CorruptTagsEvent.model_validate(
        {"id": "e1", "at": "0s", "target": "a", "flavor": "null_bytes"}
    )
    assert e.action is TimelineActionName.CORRUPT_TAGS
    assert e.flavor is TagCorruptionFlavor.NULL_BYTES and e.bytes == 64


def test_corrupt_tags_bytes_bounds():
    with pytest.raises(ValueError):
        CorruptTagsEvent.model_validate(
            {"id": "e1", "at": "0s", "target": "a", "flavor": "malformed_frame", "bytes": 0}
        )
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run python -m pytest tests/contract/test_corrupt_tags_event.py -v`
Expected: FAIL (undefined names).

- [ ] **Step 3: Add enum, action member, event, union entry**

In `scenario.py`:
```python
class TagCorruptionFlavor(enum.StrEnum):
    """Tag-corruption shape for corrupt_tags."""

    NULL_BYTES = "null_bytes"
    MALFORMED_FRAME = "malformed_frame"
```
Add `CORRUPT_TAGS = "corrupt_tags"` to `TimelineActionName`. Add the event class near the
other corruptors:
```python
class CorruptTagsEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.CORRUPT_TAGS] = TimelineActionName.CORRUPT_TAGS
    target: str
    flavor: TagCorruptionFlavor
    bytes: int = Field(default=64, ge=1, le=4096)
```
Add `| CorruptTagsEvent` to the `TimelineEvent` union.

- [ ] **Step 4: Run to verify pass + regenerate + guardrails**

Run: `uv run python -m pytest tests/contract/test_corrupt_tags_event.py -v && uv run python -m chaos_librarian.schema_export --write && uv run ruff check && uv run ty check src tests && uv run python -m pytest -q`
Expected: PASS; `scenario.schema.json` gains the variant + enum.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: add corrupt_tags event + TagCorruptionFlavor (#118)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 8: `corrupt_tags` validation wiring (profile, target, lifecycle, hierarchy)

**Files:**
- Modify: `src/chaos_librarian/validation/rules/profile_opt_in.py`
- Modify: `src/chaos_librarian/validation/rules/target_unknown.py`
- Modify: `src/chaos_librarian/validation/rules/timeline_lifecycle.py`
- Modify: `src/chaos_librarian/validation/rules/hierarchy.py`
- Test: `tests/validation/test_corrupt_tags.py`
- Create: `tests/fixtures/scenarios/invalid/corrupt-tags-missing-profile.yaml`

- [ ] **Step 1: Write the failing test**

```python
from chaos_librarian.validation.codes import E_PROFILE_REQUIRED, E_TARGET_UNKNOWN


def test_corrupt_tags_requires_malformed_media(validate_scenario):
    report = validate_scenario("corrupt-tags-missing-profile")  # invalid fixture
    assert E_PROFILE_REQUIRED in report_codes(report)
```
(Mirror the existing `corrupt-container-header-missing-profile` test pattern in
`tests/validation/`.)

- [ ] **Step 2: Run to verify failure**

Run: `uv run python -m pytest tests/validation/test_corrupt_tags.py -v`
Expected: FAIL (no gate).

- [ ] **Step 3: Wire the four rule sets**

- `profile_opt_in.py`: add
  `TimelineActionName.CORRUPT_TAGS.value: ProfileName.MALFORMED_MEDIA.value`.
- `target_unknown.py`: add `TimelineActionName.CORRUPT_TAGS` to the asset-target set
  (next to `CORRUPT_CONTAINER_HEADER`).
- `timeline_lifecycle.py`: add `TimelineActionName.CORRUPT_TAGS` to the mutation set AND
  `_SLOW_COPY_INCOMPATIBLE_OPS`.
- `hierarchy.py`: add a `CORRUPT_TAGS` branch mirroring `CORRUPT_CONTAINER_HEADER`
  (line ~499) so target resolution matches.

- [ ] **Step 4: Add the invalid corpus fixture**

`corrupt-tags-missing-profile.yaml` first line `# expected: E_PROFILE_REQUIRED`, a
minimal music scenario with a `corrupt_tags` event and **no** `malformed-media` profile.

- [ ] **Step 5: Run to verify pass + guardrails**

Run: `uv run python -m pytest tests/validation -k "corrupt_tags or invalid_corpus" -q && uv run ruff check && uv run ty check src tests && uv run python -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: validate corrupt_tags (profile, target, lifecycle) (#118)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 9: `corrupt_tags` engine handler + byte helpers

**Files:**
- Modify: `src/chaos_librarian/materializer/phase_b/corruption_bytes.py`
- Modify: `src/chaos_librarian/engine/events.py`
- Test: `tests/materializer/phase_b/test_corruption_bytes.py`
- Test: `tests/engine/test_corrupt_tags.py`

- [ ] **Step 1: Write the failing byte-helper test**

```python
import pytest
from chaos_librarian.materializer.phase_b.corruption_bytes import (
    malformed_id3_header, zero_range,
)


def test_zero_range_zeros_head():
    out = zero_range(b"abcdefgh", byte_start=0, byte_count=4)
    assert out == b"\x00\x00\x00\x00efgh" and len(out) == 8


def test_zero_range_rejects_overlong():
    with pytest.raises(ValueError):
        zero_range(b"ab", byte_start=0, byte_count=4)


def test_malformed_id3_header_in_place_and_starts_with_magic():
    out = malformed_id3_header(b"\x11" * 32, byte_count=10)
    assert out[:3] == b"ID3" and len(out) == 32 and out[10:] == b"\x11" * 22
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run python -m pytest tests/materializer/phase_b/test_corruption_bytes.py -v`
Expected: FAIL (undefined).

- [ ] **Step 3: Implement the helpers**

In `corruption_bytes.py`:
```python
def zero_range(data: bytes, *, byte_start: int, byte_count: int) -> bytes:
    """Return ``data`` with ``byte_count`` head bytes overwritten with 0x00."""
    required_length = byte_start + byte_count
    if len(data) < required_length:
        raise ValueError(
            "input file is shorter than requested corruption range: "
            f"{len(data)} < {required_length}"
        )
    output = bytearray(data)
    output[byte_start:required_length] = b"\x00" * byte_count
    return bytes(output)


_MALFORMED_ID3_HEADER: Final = bytes((0x49, 0x44, 0x33, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF))


def malformed_id3_header(data: bytes, *, byte_count: int) -> bytes:
    """Overwrite ``byte_count`` head bytes in place with a deterministic invalid ID3v2 header."""
    if len(data) < byte_count:
        raise ValueError(
            f"input file is shorter than requested header span: {len(data)} < {byte_count}"
        )
    pattern = (_MALFORMED_ID3_HEADER * (byte_count // len(_MALFORMED_ID3_HEADER) + 1))[:byte_count]
    output = bytearray(data)
    output[:byte_count] = pattern
    return bytes(output)
```
(import `Final` if not already.)

- [ ] **Step 4: Write the failing engine test**

```python
from chaos_librarian.contract.profiles import ProfileName
# Build a resolved corrupt_tags event through the engine harness (mirror
# tests/engine corrupt_container_header tests) and assert the journal entry's
# state_delta carries profile/corruptor/flavor/seed_material and the version
# binds a CorruptionRecord with metadata={"flavor": "null_bytes"}.
```

- [ ] **Step 5: Implement `_handle_corrupt_tags` + dispatch + state_delta keys**

In `events.py`, mirror `_handle_truncate_file`:
```python
def _handle_corrupt_tags(state, resolved, ids, ctx):
    event = _checked_event(resolved, CorruptTagsEvent)
    corruptor = "tag_corruption_v1"
    seed_material = _seed_material(corruptor, ctx, event.id, event.target)
    record = CorruptionRecord(
        profile=ProfileName.MALFORMED_MEDIA, event_id=event.id, corruptor=corruptor,
        byte_start=0, byte_count=event.bytes, seed_material=seed_material,
        metadata={"flavor": event.flavor.value},
    )
    prior, new = _bind_corruption_version(state, ids, target=event.target, record=record)
    loc_id = state.location_id_for_asset(event.target)
    location = state.locations[loc_id]
    return (_new_atomic_entry(
        resolved=resolved, ctx=ctx, action=TimelineActionName.CORRUPT_TAGS,
        target_ids=[event.target], location_ids=[loc_id],
        input_version_ids=[prior], output_version_ids=[new],
        state_delta={
            "input_path": location.path, "output_path": location.path,
            "profile": ProfileName.MALFORMED_MEDIA.value, "corruptor": corruptor,
            "flavor": event.flavor.value, "byte_count": event.bytes,
            "seed_material": seed_material,
        },
    ),)
```
Add `_STATE_DELTA_KEYS[CORRUPT_TAGS] = frozenset({"input_path","output_path","profile","corruptor","flavor","byte_count","seed_material"})`
and the dispatch-table entry. Import `CorruptTagsEvent`.

- [ ] **Step 6: Run + guardrails**

Run: `uv run python -m pytest tests/materializer/phase_b/test_corruption_bytes.py tests/engine/test_corrupt_tags.py -v && uv run ruff check && uv run ty check src tests && uv run python -m pytest -q`
Expected: PASS (incl. state-delta-keys contract test).

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: engine handler + byte helpers for corrupt_tags (#118)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 10: `corrupt_tags` phase-B materializer + `CorruptionAction.action`

**Files:**
- Modify: `src/chaos_librarian/contract/materialization.py` (widen `action` Literal)
- Modify: `src/chaos_librarian/materializer/phase_b/corruption.py`
- Test: `tests/materializer/phase_b/test_corrupt_tags_apply.py`
- Regenerate: `schemas/materialization.schema.json`

- [ ] **Step 1: Widen `CorruptionAction.action`**

In `materialization.py`, add `TimelineActionName.CORRUPT_TAGS` to the `action` Literal.

- [ ] **Step 2: Write the failing materializer test**

Build a `corrupt_tags` journal entry (null_bytes, bytes=8) over a small on-disk file and
assert `_apply_corrupt_tags` zeros the first 8 bytes, returns a `CorruptionAction` with
`action == corrupt_tags`, `metadata == {"flavor": "null_bytes"}`, and a `probe_outcome`.
Mirror `tests/materializer/phase_b` truncate/container tests for the harness.

- [ ] **Step 3: Run to verify failure**

Run: `uv run python -m pytest tests/materializer/phase_b/test_corrupt_tags_apply.py -v`
Expected: FAIL (`corrupt_tags` not in `_HANDLERS`).

- [ ] **Step 4: Implement `_apply_corrupt_tags`**

In `corruption.py`, add to `_CorruptionTimelineAction` the `CORRUPT_TAGS` literal, import
`malformed_id3_header`, `zero_range`, and `TagCorruptionFlavor`, then:
```python
def _apply_corrupt_tags(ctx, entry, started):
    delta = entry.state_delta
    paths = _paths_from_delta(ctx, delta)
    flavor = _state_delta_str(delta, "flavor")
    byte_count = _state_delta_int(delta, "byte_count")
    seed_material = _state_delta_str(delta, "seed_material")
    input_bytes = paths.input_path.read_bytes()
    if flavor == TagCorruptionFlavor.NULL_BYTES.value:
        output_bytes = zero_range(input_bytes, byte_start=0, byte_count=byte_count)
    else:
        output_bytes = malformed_id3_header(input_bytes, byte_count=byte_count)
    finalized = _write_bytes_and_finalize(ctx, entry, paths, input_bytes, output_bytes)
    return _corruption_action(
        entry=entry, action=TimelineActionName.CORRUPT_TAGS, finalized=finalized,
        started=started, corruptor=_state_delta_str(delta, "corruptor"),
        byte_start=0, byte_count=byte_count, seed_material=seed_material,
        metadata={"flavor": flavor},
    )
```
Register it in `_HANDLERS`.

- [ ] **Step 5: Regenerate + guardrails**

Run: `uv run python -m pytest tests/materializer/phase_b/test_corrupt_tags_apply.py -v && uv run python -m chaos_librarian.schema_export --write && uv run ruff check && uv run ty check src tests && uv run python -m pytest -q && uv run python -m chaos_librarian.schema_export --check`
Expected: PASS; `materialization.schema.json` `action` enum gains `corrupt_tags`.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: materialize corrupt_tags byte corruption (#118)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 11: Valid fixtures, recipes, smoke-corpus, and backward-compat regression

**Files:**
- Create: `tests/fixtures/scenarios/corrupt-tags.yaml`
- Create: `tests/fixtures/scenarios/cue-sidecar.yaml`
- Create: `tests/fixtures/scenarios/poster-image-format.yaml`
- Create: `recipes/metadata/corrupt-tags.yaml`
- Create: `recipes/sidecar/cue-sheet.yaml`
- Create: `recipes/sidecar/album-art-webp.yaml`
- Test: `tests/contract/test_sample_scenarios.py` (auto-loads new valid fixtures)
- Test: `tests/<recipes>/...` (recipe bit-rot guard already loads `recipes/`)

- [ ] **Step 1: Author the three valid fixtures**

Each `schema_version: 32`, a minimal music topology (one artist → album → disc → track →
variant → bundle → audio asset). `corrupt-tags.yaml` lists `profiles: [malformed-media]`
and a `corrupt_tags` event; `cue-sidecar.yaml` a `create_sidecar` `kind: cue` (+ an
`update_sidecar` to exercise the sync chaos); `poster-image-format.yaml` a `create_sidecar`
`kind: poster` `image_format: webp` `to: ...cover.webp`.

- [ ] **Step 2: Run the smoke corpus**

Run: `uv run python -m pytest tests/contract/test_sample_scenarios.py -q`
Expected: PASS (every fixture validates through `Scenario.model_validate`).

- [ ] **Step 3: Author the three recipes**

Mirror the structure of `recipes/metadata/truncated-file.yaml` (for corrupt-tags) and
`recipes/sidecar/*.yaml` (for cue / album-art). Follow ADR 0002 recipe conventions.

- [ ] **Step 4: Run the recipe bit-rot guard**

Run: `uv run python -m pytest tests/recipes -q`
Expected: PASS (recipes validate).

- [ ] **Step 5: Write the backward-compat regression test**

```python
# tests/contract/test_v32_backward_compat.py
# For a representative existing movie, TV, and podcast fixture, assert that loading
# at v32 yields a Scenario whose model_dump(mode="json") equals the v31 baseline
# except schema_version. Assert no movie/TV/podcast model gained required fields.
```
Concretely: load each fixture, dump, pop `schema_version`, and compare against a frozen
expected dict (or assert the dump is unchanged vs. a `git show HEAD~N:` baseline if the
harness supports it). At minimum assert the three new scenario fields
(`image_format`, the `cue` kind, `corrupt_tags`) are all optional/absent by default so
omitting them is byte-identical.

- [ ] **Step 6: Run + guardrails**

Run: `uv run python -m pytest tests/contract/test_v32_backward_compat.py -q && uv run ruff check && uv run ty check src tests && uv run python -m pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "test: valid fixtures, recipes, and v32 backward-compat (#118)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 12: Optional jpeg/webp capability flag + integration coverage

**Files:**
- Modify (optional): `src/chaos_librarian/materializer/tooling/capabilities.py`
- Test: `tests/integration/test_music_artifacts_real.py` (ffmpeg-gated, skips in CI)

- [ ] **Step 1: Write the ffmpeg-gated integration test**

Materialize `poster-image-format.yaml`, `cue-sidecar.yaml`, and `corrupt-tags.yaml` end
to end (guarded by the existing ffmpeg-availability skip marker). Assert: the poster
sidecar exists with `.webp` bytes (RIFF/WEBP magic) and a matching `ManifestSidecar.path`;
the CUE sidecar exists with `kind=cue`; the corrupt_tags version records a
`CorruptionRecord(metadata={"flavor": ...})` and the output file's head is corrupted.

- [ ] **Step 2: Run locally (ffmpeg present)**

Run: `uv run python -m pytest tests/integration/test_music_artifacts_real.py -v`
Expected: PASS locally; SKIP where ffmpeg/libwebp absent.

- [ ] **Step 3: (Optional) capability flag**

If a preflight signal for jpeg/webp is wanted, add
`materialize_webp_poster = ffmpeg_ok and _ffmpeg_encoder_available(ffmpeg, "libwebp")`
to the capabilities report (mirror `materialize_hevc_video`); bump
`CAPABILITIES_SCHEMA_VERSION` only if you add the field. Skip this step unless a
consumer needs the flag — YAGNI.

- [ ] **Step 4: Full guardrail sweep + commit**

Run: `uv run ruff check && uv run ruff format --check . && uv run ty check src tests && uv run python -m pytest -q && uv run python -m chaos_librarian.schema_export --check`
Expected: all PASS.

```bash
git add -A
git commit -m "test: ffmpeg integration coverage for music artifacts (#118)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-review notes

- **Spec coverage:** corrupt_tags (Tasks 7-10), CUE (Tasks 2-3), poster image_format
  (Tasks 4-6); version bumps (Task 1); validation contract (Tasks 5, 8); backward-compat
  (Task 11); manifest stays v10 (no manifest task — verified, not changed).
- **Order:** Task 1 first so the drift gate stays green; contract → validation →
  engine → materializer per capability; fixtures/recipes last once all paths exist.
- **No new error code; manifest v10; only scenario 32 + materialization 17 bump.**
- **Deferred (file as issues before merge):** album-art format-change action,
  multi-track single-file album, embedded-lyrics phase-A field.
