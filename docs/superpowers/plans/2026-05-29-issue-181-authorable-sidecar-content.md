# Authorable Sidecar Content (#181) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add authorable `codec`/`source`/`encoding` (subtitle), `body` (NFO), and
`media_type` (poster) knobs to the `create_sidecar` timeline event so the
`wrong-encoding`, `nfo-xml-injection`, and `poster-is-video` recipes become valid
scenarios, with an SRT-only timeline matrix rejecting unsynthesizable combos via
`E_MATERIALIZE_UNSUPPORTED`.

**Architecture:** Flat optional fields on `CreateSidecarEvent` gated by an extended
`model_validator` (cross-kind misuse → `E_FIELD_*`); a new semantic rule
`rule_create_sidecar_content` rejects non-SRT subtitle combos (→
`E_MATERIALIZE_UNSUPPORTED`); the engine threads the fields through `state_delta`; the
phase-B handler applies the encoding / writes the body verbatim / emits a video poster;
`LiveSidecar` + `regenerate_sidecar` carry the fields so `update_sidecar` is faithful.
`SCENARIO_SCHEMA_VERSION` bumps 23 → 24.

**Tech Stack:** Python 3.13, Pydantic v2, pytest, ffmpeg (env-gated for materialize
tests), `uv` / `ruff` / `ty`.

**Spec:** `docs/superpowers/specs/2026-05-29-issue-181-authorable-sidecar-content-design.md`
**ADR:** `docs/adr/0003-authorable-sidecar-content.md`

---

## File structure

| File | Responsibility | Action |
| --- | --- | --- |
| `src/chaos_librarian/contract/scenario.py` | `SidecarMediaType` enum; new `CreateSidecarEvent` fields + extended validator; `schema_version: Literal[24]` | Modify |
| `src/chaos_librarian/contract/__init__.py` | `SCENARIO_SCHEMA_VERSION = 24` | Modify |
| `src/chaos_librarian/validation/rules/_subtitle_recipe.py` | shared `_SRT_SUBTITLE_ENCODINGS` set + matrices | Create |
| `src/chaos_librarian/validation/rules/materialize_media_matrix.py` | import shared set/matrix (declared path) | Modify |
| `src/chaos_librarian/validation/rules/create_sidecar_content.py` | new semantic rule (timeline subtitle matrix) | Create |
| `src/chaos_librarian/validation/semantic.py` | register the new rule | Modify |
| `src/chaos_librarian/engine/events.py` | `_STATE_DELTA_KEYS` + `_handle_create_sidecar` emit new fields | Modify |
| `src/chaos_librarian/materializer/phase_b/sidecar_bytes.py` | encoding map; `regenerate_sidecar` honors encoding/body/media_type | Modify |
| `src/chaos_librarian/materializer/phase_b/media.py` | `LiveSidecar` fields; `_apply_create_sidecar` routing | Modify |
| `recipes/sidecar/wrong-encoding.yaml` etc. | three new recipes | Create |
| `tests/fixtures/scenarios/**`, `recipes/**` | bump `schema_version: 24` (146 files) | Modify |
| `schemas/scenario.schema.json` | regenerated | Modify |

---

## Task 1: Add the `SidecarMediaType` enum (no version bump yet)

> **Phase-ordering note:** the `schema_version` literal bump is deliberately NOT in this
> task. Bumping the model's `Literal[24]` while the 146 fixtures are still at 23 would
> make `test_sample_scenario_loads` (which runs `Scenario.model_validate` on every
> fixture) fail — a red commit. Task 2 bumps the model literal AND the fixtures in one
> atomic commit so no commit is ever red. This task adds only the standalone enum.

**Files:**
- Modify: `src/chaos_librarian/contract/scenario.py` (near `SidecarKind`, ~line 283)
- Test: `tests/contract/test_scenario.py`

- [ ] **Step 1: Write the failing test**

In `tests/contract/test_scenario.py`, add (import `SidecarMediaType` from
`chaos_librarian.contract.scenario` at the top alongside `SidecarKind`):

```python
def test_sidecar_media_type_enum_values():
    assert SidecarMediaType.IMAGE.value == "image"
    assert SidecarMediaType.VIDEO.value == "video"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/contract/test_scenario.py::test_sidecar_media_type_enum_values -q`
Expected: FAIL with `ImportError`/`AttributeError` for `SidecarMediaType`.

- [ ] **Step 3: Add the enum**

In `scenario.py`, after the `SidecarKind` class add:

```python
class SidecarMediaType(enum.StrEnum):
    """Synthesized media kind for a poster sidecar.

    ``image`` is the default PNG poster; ``video`` writes a small deterministic
    video at the poster path — the ``poster-is-video`` chaos.
    """

    IMAGE = "image"
    VIDEO = "video"
```

Do **not** change `schema_version` or `SCENARIO_SCHEMA_VERSION` here (see the
phase-ordering note above).

- [ ] **Step 4: Run test + full suite to verify green**

Run:
```bash
uv run python -m pytest tests/contract/test_scenario.py::test_sidecar_media_type_enum_values -q
uv run python -m pytest -q
```
Expected: the new test PASSES and the full suite stays green (the enum is unused so far,
fixtures still at 23, model still `Literal[23]`).

- [ ] **Step 5: Commit**

```bash
git add src/chaos_librarian/contract/scenario.py tests/contract/test_scenario.py
git commit -m "feat: add SidecarMediaType enum

Refs #181

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Bump model literal + all fixtures/recipes to 24 (one atomic commit)

> This task changes the model's `Literal[23]` → `Literal[24]`, the
> `SCENARIO_SCHEMA_VERSION` constant, AND every fixture/recipe in a **single commit**,
> so the tree is green before and after but never red mid-way (the model literal and the
> fixtures must move together — see the Task 1 phase-ordering note).

**Files:**
- Modify: `src/chaos_librarian/contract/scenario.py` (`schema_version` ~line 894)
- Modify: `src/chaos_librarian/contract/__init__.py:16`
- Modify: 146 files matching `schema_version: 23` under `tests/` and `recipes/`
- Modify: `schemas/scenario.schema.json` (regenerated)

- [ ] **Step 1: Confirm the file set and the one exception**

Run: `rg -l "schema_version: 23" tests recipes | wc -l`
Expected: `146`.

Run: `rg -rn "schema_version:" tests/fixtures/scenarios/invalid/yaml-parse-error.yaml`
Expected: `schema_version: 11` — this fixture expects `E_YAML_PARSE`, never parses, and
must stay at 11. It is not among the 146.

- [ ] **Step 2: Bump the model literal, the constant, and the 146 fixtures**

In `scenario.py`, change the `Scenario` field `schema_version: Literal[23]` to
`schema_version: Literal[24]`. In `contract/__init__.py`, change
`SCENARIO_SCHEMA_VERSION: Final = 23` to `= 24`. Then bulk-bump the fixtures:

```bash
rg -l "schema_version: 23" tests recipes | xargs sed -i '' 's/schema_version: 23/schema_version: 24/'
```
(On Linux CI this is `sed -i`; locally on macOS use `sed -i ''` as shown.)

Run: `rg -l "schema_version: 23" tests recipes | wc -l`
Expected: `0`.

- [ ] **Step 3: Regenerate the schema artifact**

Run: `uv run python -m chaos_librarian.schema_export --write`
Then: `git status --short schemas/`
Expected: `schemas/scenario.schema.json` modified (the `schema_version` const → 24).

- [ ] **Step 4: Run the corpus + drift gates**

Run:
```bash
uv run python -m pytest tests/contract/test_sample_scenarios.py tests/validation/test_invalid_corpus.py tests/recipes/test_recipe_corpus.py -q
uv run python -m chaos_librarian.schema_export --check
```
Expected: all PASS (drift gate exits 0).

- [ ] **Step 5: Commit (model + fixtures + schema together)**

```bash
git add src/chaos_librarian/contract/scenario.py src/chaos_librarian/contract/__init__.py tests recipes schemas
git commit -m "feat!: bump scenario schema to 24

Refs #181

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Add new fields to `CreateSidecarEvent` with cross-kind exclusivity

**Files:**
- Modify: `src/chaos_librarian/contract/scenario.py` (`CreateSidecarEvent`, ~line 578)
- Test: `tests/contract/test_scenario.py`

- [ ] **Step 1: Write the failing tests**

In `tests/contract/test_scenario.py` (import `SubtitleCodec`, `SubtitleSource`,
`SubtitleEncoding`, `SidecarMediaType` as needed):

```python
def test_create_sidecar_subtitle_accepts_codec_source_encoding():
    event = CreateSidecarEvent.model_validate({
        "id": "ev", "at": "1s", "action": "create_sidecar",
        "target": "asset_main", "to": "asset_main.eng.srt", "language": "eng",
        "codec": "srt", "source": "generated_srt", "encoding": "utf16_le",
    })
    assert event.encoding == SubtitleEncoding.UTF16_LE
    assert event.codec == SubtitleCodec.SRT


def test_create_sidecar_nfo_accepts_body():
    event = CreateSidecarEvent.model_validate({
        "id": "ev", "at": "1s", "action": "create_sidecar",
        "target": "asset_main", "to": "asset_main.nfo", "kind": "nfo",
        "body": "<movie>x</movie>",
    })
    assert event.body == "<movie>x</movie>"


def test_create_sidecar_poster_accepts_media_type():
    event = CreateSidecarEvent.model_validate({
        "id": "ev", "at": "1s", "action": "create_sidecar",
        "target": "asset_main", "to": "asset_main.poster.jpg", "kind": "poster",
        "media_type": "video",
    })
    assert event.media_type == SidecarMediaType.VIDEO


def test_create_sidecar_encoding_on_nfo_rejected():
    with pytest.raises(ValidationError, match="encoding"):
        CreateSidecarEvent.model_validate({
            "id": "ev", "at": "1s", "action": "create_sidecar",
            "target": "asset_main", "to": "x.nfo", "kind": "nfo",
            "encoding": "utf16_le",
        })


def test_create_sidecar_body_on_poster_rejected():
    with pytest.raises(ValidationError, match="body"):
        CreateSidecarEvent.model_validate({
            "id": "ev", "at": "1s", "action": "create_sidecar",
            "target": "asset_main", "to": "p.jpg", "kind": "poster",
            "body": "<x/>",
        })


def test_create_sidecar_media_type_on_subtitle_rejected():
    with pytest.raises(ValidationError, match="media_type"):
        CreateSidecarEvent.model_validate({
            "id": "ev", "at": "1s", "action": "create_sidecar",
            "target": "asset_main", "to": "x.srt", "language": "eng",
            "media_type": "video",
        })


def test_create_sidecar_empty_body_rejected():
    with pytest.raises(ValidationError):
        CreateSidecarEvent.model_validate({
            "id": "ev", "at": "1s", "action": "create_sidecar",
            "target": "asset_main", "to": "x.nfo", "kind": "nfo", "body": "",
        })
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m pytest tests/contract/test_scenario.py -q -k create_sidecar`
Expected: the seven new tests FAIL (`extra_forbidden` for the accept tests, no rejection
for the reject tests).

- [ ] **Step 3: Add the fields and extend the validator**

In `scenario.py`, replace the `CreateSidecarEvent` body. Add the fields after `kind`
and rename `_check_language_matches_kind` to `_check_fields_match_kind`:

```python
class CreateSidecarEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.CREATE_SIDECAR] = TimelineActionName.CREATE_SIDECAR
    target: str
    to: str
    language: str | None = None
    kind: SidecarKind = SidecarKind.SUBTITLE
    # Subtitle-only authoring knobs (scenario v24). None ⇒ srt/generated_srt/utf8.
    codec: SubtitleCodec | None = None
    source: SubtitleSource | None = None
    encoding: SubtitleEncoding | None = None
    # NFO-only authored body (exact UTF-8 bytes). None ⇒ render_nfo template.
    body: str | None = Field(default=None, min_length=1)
    # Poster-only synthesized media kind. None ⇒ image (PNG).
    media_type: SidecarMediaType | None = None

    @model_validator(mode="after")
    def _check_fields_match_kind(self) -> CreateSidecarEvent:
        if self.kind == SidecarKind.SUBTITLE and self.language is None:
            raise ValueError("subtitle sidecar requires language")
        if self.kind != SidecarKind.SUBTITLE and self.language is not None:
            raise ValueError(f"{self.kind.value} sidecar forbids language")
        subtitle_fields = {"codec": self.codec, "source": self.source, "encoding": self.encoding}
        if self.kind != SidecarKind.SUBTITLE:
            for name, value in subtitle_fields.items():
                if value is not None:
                    raise ValueError(f"{name} is only valid for subtitle sidecars")
        if self.kind != SidecarKind.NFO and self.body is not None:
            raise ValueError("body is only valid for nfo sidecars")
        if self.kind != SidecarKind.POSTER and self.media_type is not None:
            raise ValueError("media_type is only valid for poster sidecars")
        return self
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run python -m pytest tests/contract/test_scenario.py -q -k create_sidecar`
Expected: all PASS (including the pre-existing language/kind tests).

- [ ] **Step 5: Regenerate schema + commit**

```bash
uv run python -m chaos_librarian.schema_export --write
git add src/chaos_librarian/contract/scenario.py tests/contract/test_scenario.py schemas/scenario.schema.json
git commit -m "feat: add authorable content fields to create_sidecar event

Refs #181

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Lift the shared SRT encoding set; add the timeline matrix

**Files:**
- Create: `src/chaos_librarian/validation/rules/_subtitle_recipe.py`
- Modify: `src/chaos_librarian/validation/rules/materialize_media_matrix.py:53-61`
- Test: `tests/validation/rules/test_subtitle_recipe.py`

- [ ] **Step 1: Write the failing test**

Create `tests/validation/rules/test_subtitle_recipe.py`:

```python
from chaos_librarian.validation.rules._subtitle_recipe import (
    CREATE_SIDECAR_SUBTITLE_MATRIX,
    SRT_SUBTITLE_ENCODINGS,
    SUBTITLE_RECIPE_MATRIX,
)


def test_srt_encodings_shared():
    assert SRT_SUBTITLE_ENCODINGS == frozenset(
        {"utf8", "utf8_bom", "utf16_le", "iso_8859_1"}
    )


def test_declared_matrix_still_accepts_ass():
    assert ("ass", "styled_ass") in SUBTITLE_RECIPE_MATRIX


def test_timeline_matrix_is_srt_only():
    assert set(CREATE_SIDECAR_SUBTITLE_MATRIX) == {("srt", "generated_srt")}
    assert CREATE_SIDECAR_SUBTITLE_MATRIX[("srt", "generated_srt")] == SRT_SUBTITLE_ENCODINGS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/validation/rules/test_subtitle_recipe.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Create the shared module and rewire the declared path**

Create `src/chaos_librarian/validation/rules/_subtitle_recipe.py`:

```python
"""Shared subtitle recipe matrices for the declared and timeline paths.

The declared-subtitle path (`materialize_media_matrix`) accepts srt/ass/ssa;
the timeline `create_sidecar` path (`create_sidecar_content`) is SRT-only in v1
because `_apply_create_sidecar` does not synthesize ASS bodies. Both share the
SRT encoding set so a future encoding addition flows to both.
"""

from __future__ import annotations

from typing import Final

SRT_SUBTITLE_ENCODINGS: Final[frozenset[str]] = frozenset(
    {"utf8", "utf8_bom", "utf16_le", "iso_8859_1"}
)
_ASS_SUBTITLE_ENCODINGS: Final[frozenset[str]] = frozenset({"utf8", "utf8_bom"})

SUBTITLE_RECIPE_MATRIX: Final[dict[tuple[str, str], frozenset[str]]] = {
    ("srt", "generated_srt"): SRT_SUBTITLE_ENCODINGS,
    ("ass", "styled_ass"): _ASS_SUBTITLE_ENCODINGS,
    ("ssa", "styled_ass"): _ASS_SUBTITLE_ENCODINGS,
}

CREATE_SIDECAR_SUBTITLE_MATRIX: Final[dict[tuple[str, str], frozenset[str]]] = {
    ("srt", "generated_srt"): SRT_SUBTITLE_ENCODINGS,
}
```

In `materialize_media_matrix.py`, delete the local `_SRT_SUBTITLE_ENCODINGS`,
`_ASS_SUBTITLE_ENCODINGS`, and `_SUBTITLE_RECIPE_MATRIX` (lines 53-61) and import the
shared names, aliasing to keep the rest of the file unchanged:

```python
from chaos_librarian.validation.rules._subtitle_recipe import (
    SUBTITLE_RECIPE_MATRIX as _SUBTITLE_RECIPE_MATRIX,
)
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
uv run python -m pytest tests/validation/rules/test_subtitle_recipe.py tests/validation/ -q -k "matrix or media_matrix or invalid_corpus"
```
Expected: PASS (the declared ass+utf16 fixture still rejects via the shared matrix).

- [ ] **Step 5: Commit**

```bash
git add src/chaos_librarian/validation/rules/_subtitle_recipe.py src/chaos_librarian/validation/rules/materialize_media_matrix.py tests/validation/rules/test_subtitle_recipe.py
git commit -m "refactor: share SRT subtitle encoding set across recipe matrices

Refs #181

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: New semantic rule rejecting non-SRT timeline subtitle combos

**Files:**
- Create: `src/chaos_librarian/validation/rules/create_sidecar_content.py`
- Modify: `src/chaos_librarian/validation/semantic.py` (import + append to `_RULES`)
- Create: `tests/fixtures/scenarios/invalid/create-sidecar-ass-utf16.yaml`
- Test: `tests/validation/rules/test_create_sidecar_content.py`

- [ ] **Step 1: Write the failing test**

Create `tests/validation/rules/test_create_sidecar_content.py`. It uses the **real**
per-rule harness from `tests/validation/rules/conftest.py`: the `minimal_scenario`
builder fixture (default asset id `"a"`), `IssueCollector()`, and `run_semantic_pass`.
There is **no** `collect_issues` helper — drive the collector directly, exactly as
`test_sidecar_language.py` does:

```python
from __future__ import annotations

from chaos_librarian.scenario_io import LineIndex
from chaos_librarian.validation import codes
from chaos_librarian.validation.pipeline import IssueCollector
from chaos_librarian.validation.semantic import run_semantic_pass


def _materialize_codes(raw: dict[str, object], line_index: LineIndex) -> list[str]:
    collector = IssueCollector()
    run_semantic_pass(raw, line_index, collector)
    return [
        i.code for i in collector.issues if i.code == codes.E_MATERIALIZE_UNSUPPORTED
    ]


def _create_sidecar(extra: dict[str, object]) -> dict[str, object]:
    return {
        "id": "ev", "at": "1s", "action": "create_sidecar",
        "target": "a", "to": "r/a.eng.srt", "language": "eng", **extra,
    }


def test_srt_utf16_accepted(minimal_scenario, empty_index) -> None:
    raw = minimal_scenario(timeline=[_create_sidecar({"encoding": "utf16_le"})])
    assert _materialize_codes(raw, empty_index) == []


def test_ass_codec_rejected(minimal_scenario, empty_index) -> None:
    raw = minimal_scenario(
        timeline=[_create_sidecar({"codec": "ass", "encoding": "utf16_le"})]
    )
    assert _materialize_codes(raw, empty_index) == [codes.E_MATERIALIZE_UNSUPPORTED]
```

The load-bearing parts: the `minimal_scenario` / `empty_index` conftest fixtures,
`IssueCollector`, `run_semantic_pass`, and filtering `collector.issues` by `.code`.
`LineIndex` is imported from `chaos_librarian.scenario_io`.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/validation/rules/test_create_sidecar_content.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement the rule**

Create `src/chaos_librarian/validation/rules/create_sidecar_content.py`:

```python
"""Rule: create_sidecar authored content must be synthesizable.

Subtitle `create_sidecar` events are SRT-only in v1; an ass/ssa codec or an
out-of-set encoding raises E_MATERIALIZE_UNSUPPORTED — the same code the
declared-subtitle path raises for the analogous combo.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from chaos_librarian.contract.scenario import SidecarKind, TimelineActionName
from chaos_librarian.validation.codes import E_MATERIALIZE_UNSUPPORTED
from chaos_librarian.validation.rules._common import Reporter, _iter_timeline_events
from chaos_librarian.validation.rules._subtitle_recipe import (
    CREATE_SIDECAR_SUBTITLE_MATRIX,
)

if TYPE_CHECKING:
    from chaos_librarian.scenario_io import LineIndex
    from chaos_librarian.validation.pipeline import IssueCollector

__all__ = ["rule_create_sidecar_content"]


def rule_create_sidecar_content(
    raw: Mapping[str, object],
    line_index: LineIndex,
    collector: IssueCollector,
) -> None:
    """Reject create_sidecar subtitle combos the materializer cannot synthesize."""
    reporter = Reporter(collector=collector, line_index=line_index)
    for index, event in _iter_timeline_events(raw):
        if event.get("action") != TimelineActionName.CREATE_SIDECAR:
            continue
        if event.get("kind", SidecarKind.SUBTITLE.value) != SidecarKind.SUBTITLE.value:
            continue
        codec = event.get("codec") or "srt"
        source = event.get("source") or "generated_srt"
        encoding = event.get("encoding") or "utf8"
        if not isinstance(codec, str) or not isinstance(source, str):
            continue  # Pydantic owns the type checks
        allowed = CREATE_SIDECAR_SUBTITLE_MATRIX.get((codec, source))
        if allowed is None:
            reporter.error(
                code=E_MATERIALIZE_UNSUPPORTED,
                message=(
                    f"create_sidecar subtitle codec/source ({codec!r}, {source!r}) "
                    "is not synthesizable by the timeline event (SRT only)"
                ),
                loc=("timeline", index, "codec"),
            )
            continue
        if isinstance(encoding, str) and encoding not in allowed:
            reporter.error(
                code=E_MATERIALIZE_UNSUPPORTED,
                message=f"create_sidecar subtitle encoding {encoding!r} is not supported",
                loc=("timeline", index, "encoding"),
            )
```

In `semantic.py`, add the import near the other rule imports:

```python
from chaos_librarian.validation.rules.create_sidecar_content import (
    rule_create_sidecar_content,
)
```

and append `rule_create_sidecar_content,` to the `_RULES` list.

- [ ] **Step 4: Add the invalid fixture and run tests**

Create `tests/fixtures/scenarios/invalid/create-sidecar-ass-utf16.yaml` (first line is
the marker; full valid scenario shape except the offending event):

```yaml
# expected: E_MATERIALIZE_UNSUPPORTED
schema_version: 24
scenario_id: invalid-create-sidecar-ass-utf16
seed: 7
duration_scale: short
library:
  roots:
    - id: root_main
      path: movies
movies:
  - id: movie_bad
    title: T
    layout: movie_flat
    variants:
      - id: variant_bad
        label: hd
        bundle:
          id: bundle_bad
          assets:
            - id: asset_bad
              role: main
              container: mkv
              duration_seconds: 1.0
              video: {source: color_bars, codec: h264, resolution: hd}
              audio: [{codec: aac, channels: stereo, language: eng}]
series: []
artists: []
timeline:
  - id: ev_cs
    at: 1s
    action: create_sidecar
    target: asset_bad
    to: movies/asset_bad.eng.srt
    language: eng
    codec: ass
    encoding: utf16_le
```

Run:
```bash
uv run python -m pytest tests/validation/rules/test_create_sidecar_content.py tests/validation/test_invalid_corpus.py -q
```
Expected: PASS (the new fixture's marker matches the emitted `E_MATERIALIZE_UNSUPPORTED`).

- [ ] **Step 5: Commit**

```bash
git add src/chaos_librarian/validation/rules/create_sidecar_content.py src/chaos_librarian/validation/semantic.py tests/validation/rules/test_create_sidecar_content.py tests/fixtures/scenarios/invalid/create-sidecar-ass-utf16.yaml
git commit -m "feat: reject non-SRT create_sidecar subtitle combos at validate

Refs #181

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: Thread new fields through the engine `state_delta`

**Files:**
- Modify: `src/chaos_librarian/engine/events.py` (`_STATE_DELTA_KEYS` ~line 78;
  `_handle_create_sidecar` ~line 503)
- Test: `tests/engine/test_state_delta_contract.py` (already parametrized over
  `_STATE_DELTA_KEYS`)

- [ ] **Step 1: Extend the contract test expectation**

The existing `test_state_delta_keys_match_contract` is parametrized over
`_STATE_DELTA_KEYS` and asserts the handler emits a superset. Add an explicit lock so
the new keys are pinned. In `tests/engine/test_state_delta_contract.py`, after
`test_corruption_state_delta_contract_keys`, add:

```python
def test_create_sidecar_state_delta_contract_keys() -> None:
    assert _STATE_DELTA_KEYS[TimelineActionName.CREATE_SIDECAR] == frozenset(
        {"sidecar_path", "sidecar_id", "language", "kind",
         "codec", "source", "encoding", "body", "media_type"}
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/engine/test_state_delta_contract.py::test_create_sidecar_state_delta_contract_keys -q`
Expected: FAIL (current frozenset has only 4 keys).

- [ ] **Step 3: Update the contract and the handler**

In `events.py`, change the `CREATE_SIDECAR` entry of `_STATE_DELTA_KEYS` to:

```python
    TimelineActionName.CREATE_SIDECAR: frozenset(
        {"sidecar_path", "sidecar_id", "language", "kind",
         "codec", "source", "encoding", "body", "media_type"}
    ),
```

In `_handle_create_sidecar`, extend `state_delta` to carry the new fields (enums →
`.value` when set, else `None`):

```python
    state_delta: dict[str, object] = {
        "sidecar_path": event.to,
        "sidecar_id": sidecar_id,
        "language": event.language,
        "kind": event.kind.value,
        "codec": event.codec.value if event.codec is not None else None,
        "source": event.source.value if event.source is not None else None,
        "encoding": event.encoding.value if event.encoding is not None else None,
        "body": event.body,
        "media_type": event.media_type.value if event.media_type is not None else None,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run python -m pytest tests/engine/test_state_delta_contract.py -q`
Expected: PASS (the parametrized superset check + the new explicit lock).

- [ ] **Step 5: Commit**

```bash
git add src/chaos_librarian/engine/events.py tests/engine/test_state_delta_contract.py
git commit -m "feat: emit create_sidecar content fields in engine state_delta

Refs #181

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: Encoding map + body/media_type in `sidecar_bytes`

**Files:**
- Modify: `src/chaos_librarian/materializer/phase_b/sidecar_bytes.py`
- Test: `tests/materializer/test_sidecar_bytes.py` (create if absent; otherwise extend)

- [ ] **Step 1: Write the failing tests**

Create/extend `tests/materializer/test_sidecar_bytes.py`:

```python
from chaos_librarian.materializer.phase_b.sidecar_bytes import (
    encode_subtitle_body,
    render_nfo,
)


def test_encode_subtitle_default_is_utf8():
    assert encode_subtitle_body("héllo", None) == "héllo".encode("utf-8")


def test_encode_subtitle_utf16_le():
    assert encode_subtitle_body("hi", "utf16_le") == "hi".encode("utf-16-le")


def test_encode_subtitle_utf8_bom():
    out = encode_subtitle_body("hi", "utf8_bom")
    assert out.startswith(b"\xef\xbb\xbf")
    assert out[3:] == "hi".encode("utf-8")


def test_encode_subtitle_iso_8859_1():
    assert encode_subtitle_body("café", "iso_8859_1") == "café".encode("iso-8859-1")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m pytest tests/materializer/test_sidecar_bytes.py -q`
Expected: FAIL with `ImportError` for `encode_subtitle_body`.

- [ ] **Step 3: Implement the encoding map and update `regenerate_sidecar`**

In `sidecar_bytes.py`, add the map and helper, and add it to `__all__`:

```python
_SUBTITLE_PYTHON_ENCODING: Final[dict[str, str]] = {
    "utf8": "utf-8",
    "utf8_bom": "utf-8",
    "utf16_le": "utf-16-le",
    "iso_8859_1": "iso-8859-1",
}


def encode_subtitle_body(text: str, encoding: str | None) -> bytes:
    """Encode an SRT body. ``None`` ⇒ utf8. ``utf8_bom`` prepends a UTF-8 BOM."""
    name = encoding or "utf8"
    python_codec = _SUBTITLE_PYTHON_ENCODING.get(name)
    if python_codec is None:
        raise ValueError(f"unsupported subtitle encoding {name!r}")
    body = text.encode(python_codec)
    if name == "utf8_bom":
        return b"\xef\xbb\xbf" + body
    return body
```

(Add `from typing import Final` if not already imported.)

Update `regenerate_sidecar`'s signature to accept `encoding`, `body`, and `media_type`,
and apply them. Replace the subtitle and NFO branches:

```python
def regenerate_sidecar(
    *,
    kind: SidecarKind,
    language: str | None,
    sidecar_id: str,
    resolved_seed: int,
    event_id: str,
    duration_s: float,
    output_path: Path | None = None,
    encoding: str | None = None,
    body: str | None = None,
    media_type: str | None = None,
) -> tuple[bytes | None, list[str] | None]:
    perturbed_seed = perturbed_seed_for_update(
        sidecar_id=sidecar_id, event_id=event_id, resolved_seed=resolved_seed,
    )
    if kind == SidecarKind.SUBTITLE:
        if language is None:
            raise ValueError("subtitle sidecar requires language")
        text = srt_payload(language=language, duration_s=duration_s, seed=perturbed_seed)
        return encode_subtitle_body(text, encoding), None
    if kind == SidecarKind.NFO:
        if body is not None:
            return body.encode("utf-8"), None
        return render_nfo(sidecar_id=sidecar_id), None
    if kind == SidecarKind.POSTER:
        if output_path is None:
            raise ValueError("poster regeneration requires output_path")
        argv = poster_ffmpeg_argv(
            output_path=output_path,
            resolved_seed=perturbed_seed,
            sidecar_id=sidecar_id,
            media_type=media_type,
        )
        return None, argv
    raise ValueError(f"unknown sidecar kind {kind!r}")
```

Update `poster_ffmpeg_argv` to accept `media_type` and branch image vs video:

```python
def poster_ffmpeg_argv(
    *,
    output_path: Path,
    resolved_seed: int,
    sidecar_id: str,
    media_type: str | None = None,
) -> list[str]:
    seed_hash = _seed_hash(stream="poster_color", seed=resolved_seed, keys=(sidecar_id,))
    color = f"{seed_hash & 0xFFFFFF:06x}"
    if media_type == "video":
        return [
            "ffmpeg", "-hide_banner", "-y",
            "-f", "lavfi",
            "-i", f"color=c=#{color}:s=320x240:d=0.04:r=25",
            "-frames:v", "1",
            "-pix_fmt", "yuv420p",
            str(output_path),
        ]
    return [
        "ffmpeg", "-hide_banner", "-y",
        "-f", "lavfi",
        "-i", f"color=c=#{color}:s=400x600:d=0.01:r=1",
        "-frames:v", "1",
        str(output_path),
    ]
```

> The container is taken from `output_path`'s extension by ffmpeg's muxer
> auto-detection; for a `video` poster the recipe writes a `.mkv`/`.mp4` poster path so
> the muxer picks a video container. (A `.jpg` path with video bytes is the chaos for
> the recipe — ffmpeg will mux a single-frame video into whatever the extension implies;
> the recipe uses a video extension to keep ffmpeg happy while the *kind* says poster.)

Add `encode_subtitle_body` to `__all__`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run python -m pytest tests/materializer/test_sidecar_bytes.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/chaos_librarian/materializer/phase_b/sidecar_bytes.py tests/materializer/test_sidecar_bytes.py
git commit -m "feat: subtitle encoding map and authored body/media_type in regen

Refs #181

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 8: Apply the fields in the phase-B `_apply_create_sidecar` + `LiveSidecar`

**Files:**
- Modify: `src/chaos_librarian/materializer/phase_b/media.py` (`LiveSidecar` ~line 74;
  `_apply_create_sidecar` ~line 900; `_apply_update_sidecar` ~line 820)
- Test: `tests/materializer/test_media.py`

- [ ] **Step 1: Write the failing tests**

Read `tests/materializer/test_media.py` for the existing `_apply_create_sidecar`
harness (how it builds a `JournalEntry` + `MediaPhaseBContext`). Add a backward-compat
test (no ffmpeg) and an encoding test:

```python
def test_create_sidecar_subtitle_default_encoding_is_byte_identical(tmp_path):
    # Build a create_sidecar journal entry with no codec/source/encoding and
    # assert the written bytes equal srt_payload(...).encode("utf-8").
    # (Use the existing test harness in this file to construct ctx + entry.)
    ...


def test_create_sidecar_subtitle_utf16_le(tmp_path):
    # Same entry but encoding="utf16_le"; assert the file decodes as utf-16-le
    # and differs from the utf-8 form.
    ...


def test_create_sidecar_nfo_body_written_verbatim(tmp_path):
    # kind=nfo, body="<movie>INJECT</movie>"; assert file bytes == body.encode("utf-8").
    ...
```

Fill the `...` using the file's existing helper that runs `_apply_create_sidecar`
against a `tmp_path` library root. The subtitle/NFO branches are pure-Python (no
ffmpeg), so these run unconditionally; the poster-video path stays under the existing
ffmpeg env gate.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m pytest tests/materializer/test_media.py -q -k create_sidecar`
Expected: the new tests FAIL (encoding/body not yet applied).

- [ ] **Step 3: Update `LiveSidecar` and the handlers**

In `media.py`, widen `LiveSidecar`:

```python
@dataclass(frozen=True, slots=True)
class LiveSidecar:
    kind: SidecarKind
    language: str | None
    asset_id: str
    encoding: str | None = None
    body: str | None = None
    media_type: str | None = None
```

`make_media_phase_b_context` seeds `LiveSidecar` from `ManifestSidecar`, which has no
encoding/body/media_type — leave those `None` for initial sidecars (a pre-existing
declared sidecar updated before any create has default behavior, unchanged).

In `_apply_create_sidecar`, read the new delta fields and route:

```python
    encoding = delta.get("encoding")
    encoding = str(encoding) if isinstance(encoding, str) else None
    body = delta.get("body")
    body = str(body) if isinstance(body, str) else None
    media_type = delta.get("media_type")
    media_type = str(media_type) if isinstance(media_type, str) else None
    ...
    if kind == SidecarKind.SUBTITLE:
        if language is None:
            raise MediaActionError(...)  # unchanged
        text = srt_payload(
            language=language, duration_s=asset.duration_seconds, seed=ctx.resolved_seed,
        )
        temp_output.write_bytes(encode_subtitle_body(text, encoding))
    elif kind == SidecarKind.NFO:
        if body is not None:
            temp_output.write_bytes(body.encode("utf-8"))
        else:
            temp_output.write_bytes(render_nfo(sidecar_id=sidecar_id))
    elif kind == SidecarKind.POSTER:
        argv = poster_ffmpeg_argv(
            output_path=temp_output,
            resolved_seed=ctx.resolved_seed,
            sidecar_id=sidecar_id,
            media_type=media_type,
        )
        invocation_index = _run_ffmpeg_checked(...)  # unchanged
```

Import `encode_subtitle_body` from `sidecar_bytes` at the top of `media.py`.

Store the fields on the live sidecar:

```python
    ctx.live_sidecars[sidecar_id] = LiveSidecar(
        kind=kind, language=language, asset_id=asset_id,
        encoding=encoding, body=body, media_type=media_type,
    )
```

In `_apply_update_sidecar`, pass the stored fields into `regenerate_sidecar`:

```python
    bytes_, argv = regenerate_sidecar(
        kind=sidecar.kind,
        language=sidecar.language,
        sidecar_id=sidecar_id,
        resolved_seed=ctx.resolved_seed,
        event_id=entry.event_id,
        duration_s=asset.duration_seconds,
        output_path=temp_output,
        encoding=sidecar.encoding,
        body=sidecar.body,
        media_type=sidecar.media_type,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run python -m pytest tests/materializer/test_media.py -q`
Expected: PASS (pure-Python subtitle/NFO tests; poster-video gated as before).

- [ ] **Step 5: Commit**

```bash
git add src/chaos_librarian/materializer/phase_b/media.py tests/materializer/test_media.py
git commit -m "feat: apply authored encoding/body/media_type in create_sidecar

Refs #181

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 9: Add an `update_sidecar`-survives-authoring test

**Files:**
- Test: `tests/materializer/test_media.py`

- [ ] **Step 1: Write the failing test**

```python
def test_update_sidecar_preserves_authored_encoding(tmp_path):
    # create_sidecar subtitle encoding=utf16_le, then update_sidecar the same id;
    # assert the updated file still decodes as utf-16-le (cue text may differ).
    ...


def test_update_sidecar_preserves_authored_nfo_body(tmp_path):
    # create_sidecar nfo body="<movie>X</movie>", then update_sidecar; assert the
    # updated bytes still equal body.encode("utf-8").
    ...
```

Build these with the existing harness: run `_apply_create_sidecar` then
`_apply_update_sidecar` against the same `ctx` (so `ctx.live_sidecars` carries the
authored fields).

- [ ] **Step 2: Run tests to verify they fail or pass**

Run: `uv run python -m pytest tests/materializer/test_media.py -q -k update_sidecar`
Expected: PASS if Task 8 wired `LiveSidecar` correctly; if FAIL, fix the threading in
Task 8 before continuing (these tests lock the spec's update semantics).

- [ ] **Step 3: Commit**

```bash
git add tests/materializer/test_media.py
git commit -m "test: update_sidecar preserves authored encoding and body

Refs #181

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 10: Ship the three recipes

**Files:**
- Create: `recipes/sidecar/wrong-encoding.yaml`
- Create: `recipes/sidecar/nfo-xml-injection.yaml`
- Create: `recipes/sidecar/poster-is-video.yaml`
- Modify: `recipes/README.md` (sidecar table — add three rows)
- Test: `tests/recipes/test_recipe_corpus.py` (existing; validates clean)

- [ ] **Step 1: Read an existing sidecar recipe for the header shape**

Run: `cat recipes/sidecar/poster-and-nfo.yaml`
(Confirm the `# Recipe:` … `# Requires:` header block and overall scenario shape.)

- [ ] **Step 2: Create `wrong-encoding.yaml`**

```yaml
# Recipe: Wrong Subtitle Encoding
# Category: sidecar
# Tests: a subtitle sidecar is written in UTF-16-LE instead of the usual UTF-8.
# Expected consumer response: converges — decode the declared/sniffed encoding;
#   do not assume UTF-8.
# Requires: none
schema_version: 24
scenario_id: recipe-sidecar-wrong-encoding
seed: 1811
duration_scale: short
library:
  roots:
    - id: main
      path: movies
movies:
  - id: w_we
    title: Wrong Encoding
    layout: movie_flat
    variants:
      - id: v_we
        label: hd
        bundle:
          id: b_we
          assets:
            - id: asset_we
              role: main
              container: mkv
              duration_seconds: 2.0
              video: {source: color_bars, codec: h264, resolution: hd}
              audio:
                - {source: sine, codec: aac, channels: stereo, language: eng}
series: []
artists: []
timeline:
  - id: ev_subs
    at: 1s
    action: create_sidecar
    target: asset_we
    to: movies/Wrong Encoding - hd.eng.srt
    kind: subtitle
    language: eng
    encoding: utf16_le
```

- [ ] **Step 3: Create `nfo-xml-injection.yaml`**

```yaml
# Recipe: NFO XML Injection
# Category: sidecar
# Tests: an NFO sidecar carries an author-supplied body with an XML payload.
# Expected consumer response: errors or diverges — a hardened parser rejects or
#   neutralizes the payload; do not expand external entities.
# Requires: none
schema_version: 24
scenario_id: recipe-sidecar-nfo-xml-injection
seed: 1812
duration_scale: short
library:
  roots:
    - id: main
      path: movies
movies:
  - id: w_nx
    title: Nfo Injection
    layout: movie_flat
    variants:
      - id: v_nx
        label: hd
        bundle:
          id: b_nx
          assets:
            - id: asset_nx
              role: main
              container: mkv
              duration_seconds: 2.0
              video: {source: color_bars, codec: h264, resolution: hd}
              audio:
                - {source: sine, codec: aac, channels: stereo, language: eng}
series: []
artists: []
timeline:
  - id: ev_nfo
    at: 1s
    action: create_sidecar
    target: asset_nx
    to: movies/Nfo Injection - hd.nfo
    kind: nfo
    body: |
      <?xml version="1.0" encoding="UTF-8"?>
      <!DOCTYPE movie [<!ENTITY xxe "injected">]>
      <movie><title>&xxe;</title></movie>
```

- [ ] **Step 4: Create `poster-is-video.yaml`**

```yaml
# Recipe: Poster Is Video
# Category: sidecar
# Tests: a poster sidecar whose bytes are a video container, not an image.
# Expected consumer response: errors or diverges — detect the media kind by
#   content, not by extension; do not treat it as artwork.
# Requires: none
schema_version: 24
scenario_id: recipe-sidecar-poster-is-video
seed: 1813
duration_scale: short
library:
  roots:
    - id: main
      path: movies
movies:
  - id: w_pv
    title: Poster Is Video
    layout: movie_flat
    variants:
      - id: v_pv
        label: hd
        bundle:
          id: b_pv
          assets:
            - id: asset_pv
              role: main
              container: mkv
              duration_seconds: 2.0
              video: {source: color_bars, codec: h264, resolution: hd}
              audio:
                - {source: sine, codec: aac, channels: stereo, language: eng}
series: []
artists: []
timeline:
  - id: ev_poster
    at: 1s
    action: create_sidecar
    target: asset_pv
    to: movies/Poster Is Video - hd.poster.mkv
    kind: poster
    media_type: video
```

- [ ] **Step 5: Add the three rows to `recipes/README.md`**

Read `recipes/README.md`, find the `### recipes/sidecar/` table, and append three rows
matching the existing column layout (recipe path · what it tests · expected consumer
response · required profile). Use the header text above for each.

- [ ] **Step 6: Run the corpus test**

Run: `uv run python -m pytest tests/recipes/test_recipe_corpus.py -q`
Expected: PASS — `recipes/sidecar/` now has 6 recipes and all validate clean.

- [ ] **Step 7: Commit**

```bash
git add recipes/sidecar/wrong-encoding.yaml recipes/sidecar/nfo-xml-injection.yaml recipes/sidecar/poster-is-video.yaml recipes/README.md
git commit -m "feat: ship wrong-encoding, nfo-injection, poster-is-video recipes

Refs #181

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 11: File the follow-up issue and full guardrail sweep

**Files:** none (issue + verification)

- [ ] **Step 1: File the timeline-ASS-synthesis follow-up (AGENTS.md Rule 13)**

```bash
gh issue create \
  --title "Timeline create_sidecar ASS/SSA subtitle synthesis" \
  --body "Surfaced by #181. The timeline create_sidecar event accepts ass/ssa codecs as shape-valid but rejects them at validate time with E_MATERIALIZE_UNSUPPORTED because _apply_create_sidecar only synthesizes SRT bodies. Add ASS/SSA body synthesis to the timeline handler and widen CREATE_SIDECAR_SUBTITLE_MATRIX (src/chaos_librarian/validation/rules/_subtitle_recipe.py) to accept the ass/ssa rows."
```

Record the returned issue number; reference it in the PR body.

- [ ] **Step 2: Full guardrail sweep**

Run:
```bash
uv run ruff check
uv run ruff format --check .
uv run ty check src
uv run python -m pytest -q
uv run python -m chaos_librarian.schema_export --check
```
Expected: all green, zero warnings, drift gate exits 0.

- [ ] **Step 3: Commit any format fixups (if `ruff format` changed files)**

```bash
uv run ruff format .
git add -A
git commit -m "style: ruff format

Refs #181

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

(Skip if the tree is clean.)

---

## Verification checklist (spec coverage)

- [ ] `SidecarMediaType` enum + `schema_version: Literal[24]` + `SCENARIO_SCHEMA_VERSION = 24` (Task 1)
- [ ] 146 fixtures/recipes bumped; yaml-parse-error untouched; schema regenerated (Task 2)
- [ ] `codec`/`source`/`encoding`/`body`/`media_type` fields + cross-kind `E_FIELD_*` (Task 3)
- [ ] shared SRT encoding set; SRT-only timeline matrix (Task 4)
- [ ] `rule_create_sidecar_content` → `E_MATERIALIZE_UNSUPPORTED`; invalid fixture (Task 5)
- [ ] `state_delta` carries the five fields; contract test locked (Task 6)
- [ ] encoding map (utf8/utf8_bom/utf16_le/iso_8859_1) + body/media_type in regen (Task 7)
- [ ] handler applies encoding/body/media_type; `LiveSidecar` widened (Task 8)
- [ ] `update_sidecar` preserves authored encoding/body (Task 9)
- [ ] three recipes ship + README rows; corpus green (Task 10)
- [ ] follow-up issue filed; full guardrail sweep green (Task 11)
