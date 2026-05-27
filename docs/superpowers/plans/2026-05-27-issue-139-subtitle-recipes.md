# Subtitle Encoding, Styling, and Timing Recipes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic sidecar subtitle encoding, ASS/SSA styling, and timing-chaos recipes for declared subtitle tracks.

**Architecture:** Scenario v23 adds explicit subtitle codec, encoding, source, and timing fields. Validation and preflight enforce one recipe matrix, path rendering uses the declared subtitle codec for sidecar extensions, and materialization writes byte-exact sidecars through a pure subtitle recipe module. Timeline-created subtitle sidecars remain default generated UTF-8 SRT; validation rejects update/embed operations against non-default declared subtitle recipes.

**Tech Stack:** Python 3.13, Pydantic v2, JSON Schema export, pytest, ruff, ty, Typer materializer contracts.

---

## File Map

- Modify `src/chaos_librarian/contract/scenario.py`: add `SubtitleCodec`, `SubtitleEncoding`, `SubtitleTimingProfile`; extend `SubtitleSource`; update `SubtitleTrack`; bump scenario literal to `23`.
- Modify `src/chaos_librarian/contract/__init__.py`: bump `SCENARIO_SCHEMA_VERSION` to `23`.
- Modify `src/chaos_librarian/path_rendering.py`: add optional codec extension to `render_declared_sidecar_path`.
- Modify declared-sidecar callers in `src/chaos_librarian/engine/state.py`, `src/chaos_librarian/engine/events.py`, `src/chaos_librarian/validation/rules/_common.py`, `src/chaos_librarian/validation/rules/asset_path_safety.py`, `src/chaos_librarian/validation/rules/sidecar_target.py`, `src/chaos_librarian/validation/rules/timeline_lifecycle.py`, and `src/chaos_librarian/materializer/synthesis.py`.
- Modify `src/chaos_librarian/validation/rules/materialize_media_matrix.py`: validate subtitle recipe matrix.
- Modify `src/chaos_librarian/materializer/preflight.py`: mirror subtitle recipe matrix.
- Create `src/chaos_librarian/materializer/tooling/subtitles.py`: pure subtitle recipe renderer and encoder.
- Modify `src/chaos_librarian/materializer/synthesis.py`: write declared subtitle sidecar bytes and byte hashes.
- Modify docs and generated schemas: `docs/contract/schema-reference.md`, `schemas/scenario.schema.json`.
- Add/update tests under `tests/contract/`, `tests/validation/rules/`, `tests/materializer/`, and fixtures under `tests/fixtures/scenarios/`.

---

### Task 1: Contract and Codec-Aware Sidecar Paths

**Files:**
- Modify: `src/chaos_librarian/contract/scenario.py`
- Modify: `src/chaos_librarian/contract/__init__.py`
- Modify: `src/chaos_librarian/path_rendering.py`
- Modify: `src/chaos_librarian/engine/state.py`
- Test: `tests/contract/test_scenario.py`
- Test: `tests/contract/test_contract_constants.py`
- Test: `tests/contract/test_hierarchy_path_rendering.py`

- [x] **Step 1: Write failing contract tests**

Add to `tests/contract/test_scenario.py`:

```python
def test_subtitle_track_accepts_new_recipe_fields() -> None:
    payload = _minimal_scenario().model_dump(mode="json")
    asset = payload["movies"][0]["variants"][0]["bundle"]["assets"][0]
    asset["subtitles"] = [
        {
            "codec": "ass",
            "source": "styled_ass",
            "language": "jpn",
            "mode": "sidecar",
            "encoding": "utf8_bom",
            "timing_profile": "overlap",
        }
    ]

    scenario = Scenario.model_validate(payload)
    loaded = scenario.movies[0].variants[0].bundle.assets[0].subtitles[0]

    assert loaded.codec is SubtitleCodec.ASS
    assert loaded.source is SubtitleSource.STYLED_ASS
    assert loaded.encoding is SubtitleEncoding.UTF8_BOM
    assert loaded.timing_profile is SubtitleTimingProfile.OVERLAP


def test_subtitle_track_defaults_to_plain_utf8_srt() -> None:
    subtitle = SubtitleTrack(codec="srt", language="eng", mode="sidecar")

    assert subtitle.codec is SubtitleCodec.SRT
    assert subtitle.source is SubtitleSource.GENERATED_SRT
    assert subtitle.encoding is SubtitleEncoding.UTF8
    assert subtitle.timing_profile is SubtitleTimingProfile.NORMAL
```

Add imports for `SubtitleCodec`, `SubtitleEncoding`, and `SubtitleTimingProfile`.

Add to `tests/contract/test_contract_constants.py`:

```python
def test_issue_139_schema_versions() -> None:
    assert SCENARIO_SCHEMA_VERSION == 23
    assert MATERIALIZATION_SCHEMA_VERSION == 15
    assert REPLAY_BUNDLE_SCHEMA_VERSION == 12
    assert CAPABILITIES_SCHEMA_VERSION == 7
```

Update existing v22-specific contract tests and names to v23 where they assert
the current scenario version.

- [x] **Step 2: Write failing path-rendering tests**

Add to `tests/contract/test_hierarchy_path_rendering.py`:

```python
def test_declared_sidecar_path_uses_codec_extension() -> None:
    assert render_declared_sidecar_path("TV/Starline/Pilot.mkv", "jpn", codec="ass") == (
        "TV/Starline/Pilot.jpn.ass"
    )
    assert render_declared_sidecar_path("TV/Starline/Pilot.mkv", "spa", codec="ssa") == (
        "TV/Starline/Pilot.spa.ssa"
    )
```

- [x] **Step 3: Run tests to verify red**

Run:

```bash
uv run pytest --no-cov \
  tests/contract/test_scenario.py::test_subtitle_track_accepts_new_recipe_fields \
  tests/contract/test_scenario.py::test_subtitle_track_defaults_to_plain_utf8_srt \
  tests/contract/test_contract_constants.py::test_issue_139_schema_versions \
  tests/contract/test_hierarchy_path_rendering.py::test_declared_sidecar_path_uses_codec_extension \
  -q
```

Expected: missing enum/fields and path-rendering signature failures.

- [x] **Step 4: Implement contract enums and path rendering**

In `src/chaos_librarian/contract/scenario.py`, add:

```python
class SubtitleCodec(enum.StrEnum):
    """Sidecar subtitle codec/format."""

    SRT = "srt"
    ASS = "ass"
    SSA = "ssa"


class SubtitleEncoding(enum.StrEnum):
    """Text encoding for generated sidecar subtitle bytes."""

    UTF8 = "utf8"
    UTF8_BOM = "utf8_bom"
    UTF16_LE = "utf16_le"
    ISO_8859_1 = "iso_8859_1"


class SubtitleTimingProfile(enum.StrEnum):
    """Timing profile for generated subtitle cues."""

    NORMAL = "normal"
    OVERLAP = "overlap"
    OUT_OF_RANGE = "out_of_range"
```

Extend `SubtitleSource`:

```python
STYLED_ASS = "styled_ass"
```

Change `SubtitleTrack`:

```python
class SubtitleTrack(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source: SubtitleSource = SubtitleSource.GENERATED_SRT
    codec: SubtitleCodec
    language: str
    mode: SubtitleMode
    encoding: SubtitleEncoding = SubtitleEncoding.UTF8
    timing_profile: SubtitleTimingProfile = SubtitleTimingProfile.NORMAL
```

Change `Scenario.schema_version` to `Literal[23]` and `SCENARIO_SCHEMA_VERSION: Final = 23`.

In `src/chaos_librarian/path_rendering.py`, change:

```python
def render_declared_sidecar_path(media_path: str, language: str, *, codec: str = "srt") -> str:
    """Render the declared sidecar path next to the media stem."""
    media_path = _validate_relative_posix_path(media_path)
    language = clean_display_component(language)
    codec = _clean_asset_container(codec)
    directory, directory_separator, filename = media_path.rpartition("/")
    stem, separator, extension = filename.rpartition(".")
    if not separator or not extension:
        raise ValueError("media_path must include a file extension")
    parent = f"{directory}{directory_separator}"
    return _validate_relative_posix_path(f"{parent}{stem}.{language}.{codec}")
```

In `src/chaos_librarian/engine/state.py`, pass `codec=subtitle.codec.value` when rendering declared sidecars.

- [x] **Step 5: Run green tests and commit**

Run:

```bash
uv run pytest --no-cov \
  tests/contract/test_scenario.py::test_subtitle_track_accepts_new_recipe_fields \
  tests/contract/test_scenario.py::test_subtitle_track_defaults_to_plain_utf8_srt \
  tests/contract/test_contract_constants.py::test_issue_139_schema_versions \
  tests/contract/test_hierarchy_path_rendering.py::test_declared_sidecar_path_uses_codec_extension \
  -q
uv run ruff check src/chaos_librarian/contract src/chaos_librarian/path_rendering.py tests/contract
```

Commit:

```bash
git add src/chaos_librarian/contract src/chaos_librarian/path_rendering.py src/chaos_librarian/engine/state.py tests/contract
git commit -m "Add subtitle recipe contract fields"
```

Run one adversarial review pass on the contract/path diff before continuing.

---

### Task 2: Validation Matrix and Sidecar Projection Metadata

**Files:**
- Modify: `src/chaos_librarian/validation/rules/_common.py`
- Modify: `src/chaos_librarian/validation/rules/asset_path_safety.py`
- Modify: `src/chaos_librarian/validation/rules/sidecar_target.py`
- Modify: `src/chaos_librarian/validation/rules/timeline_lifecycle.py`
- Modify: `src/chaos_librarian/validation/rules/materialize_media_matrix.py`
- Test: `tests/validation/rules/test_materialize_media_matrix.py`
- Test: `tests/validation/rules/test_sidecar_target.py`
- Test: `tests/validation/rules/test_timeline_lifecycle.py`

- [x] **Step 1: Write failing validation matrix tests**

Add to `tests/validation/rules/test_materialize_media_matrix.py`:

```python
@pytest.mark.parametrize(
    ("codec", "source", "encoding", "timing_profile"),
    [
        ("srt", "generated_srt", "utf8_bom", "normal"),
        ("srt", "generated_srt", "utf16_le", "overlap"),
        ("srt", "generated_srt", "iso_8859_1", "out_of_range"),
        ("ass", "styled_ass", "utf8", "overlap"),
        ("ssa", "styled_ass", "utf8_bom", "out_of_range"),
    ],
)
def test_subtitle_recipe_matrix_accepts_supported_combinations(
    tmp_path: Path,
    codec: str,
    source: str,
    encoding: str,
    timing_profile: str,
) -> None:
    scenario = tmp_path / "scenario.yaml"
    _write_movie_scenario(
        scenario,
        subtitles=True,
        subtitle_codec=codec,
        subtitle_source=source,
        subtitle_encoding=encoding,
        subtitle_timing_profile=timing_profile,
    )

    report = run_validation(prepare_run_input(scenario))

    assert report.ok


@pytest.mark.parametrize(
    ("codec", "source", "encoding", "field_suffix"),
    [
        ("srt", "styled_ass", "utf8", ".subtitles[0].source"),
        ("ass", "generated_srt", "utf8", ".subtitles[0].source"),
        ("ass", "styled_ass", "utf16_le", ".subtitles[0].encoding"),
        ("ssa", "styled_ass", "iso_8859_1", ".subtitles[0].encoding"),
    ],
)
def test_subtitle_recipe_matrix_rejects_unsupported_combinations(
    tmp_path: Path,
    codec: str,
    source: str,
    encoding: str,
    field_suffix: str,
) -> None:
    scenario = tmp_path / "scenario.yaml"
    _write_movie_scenario(
        scenario,
        subtitles=True,
        subtitle_codec=codec,
        subtitle_source=source,
        subtitle_encoding=encoding,
    )

    report = run_validation(prepare_run_input(scenario))

    assert not report.ok
    assert any(issue.code == E_MATERIALIZE_UNSUPPORTED for issue in report.issues)
    assert report.issues[0].path.endswith(field_suffix)
```

Extend the local scenario writer helper with optional `subtitle_codec`,
`subtitle_source`, `subtitle_encoding`, and `subtitle_timing_profile` arguments.

- [x] **Step 2: Write failing timeline target tests**

Add to `tests/validation/rules/test_sidecar_target.py`:

```python
@pytest.mark.parametrize("action", ["update_sidecar", "embed_subtitle"])
def test_non_default_declared_subtitle_recipe_rejects_mutating_timeline_action(action: str) -> None:
    raw = _base_movie_raw()
    asset = raw["movies"][0]["variants"][0]["bundle"]["assets"][0]
    asset["subtitles"] = [
        {
            "codec": "ass",
            "source": "styled_ass",
            "language": "jpn",
            "mode": "sidecar",
        }
    ]
    event = {
        "id": "ev_sidecar",
        "at": "1s",
        "action": action,
        "target": "asset_main",
        "sidecar_path": "Static Movie - hd.jpn.ass",
    }
    raw["timeline"] = [event]

    issues = _issues_for(raw)

    assert any(issue.code == E_MATERIALIZE_UNSUPPORTED for issue in issues)
```

Add a hierarchy rerender assertion that a declared ASS sidecar path rerenders to
`.ass` after a hierarchy move/rename.

- [x] **Step 3: Run tests to verify red**

Run:

```bash
uv run pytest --no-cov \
  tests/validation/rules/test_materialize_media_matrix.py::test_subtitle_recipe_matrix_accepts_supported_combinations \
  tests/validation/rules/test_materialize_media_matrix.py::test_subtitle_recipe_matrix_rejects_unsupported_combinations \
  tests/validation/rules/test_sidecar_target.py::test_non_default_declared_subtitle_recipe_rejects_mutating_timeline_action \
  -q
```

Expected: helper/signature failures and missing validation errors.

- [x] **Step 4: Implement declared-sidecar metadata projection**

In `src/chaos_librarian/validation/rules/_common.py`, extend `DeclaredSidecar`:

```python
@dataclass(frozen=True, slots=True)
class DeclaredSidecar:
    asset_id: str
    path: str
    kind: str
    language: str | None
    codec: str = "srt"
    source: str = "generated_srt"
    encoding: str = "utf8"
    timing_profile: str = "normal"

    @property
    def uses_default_subtitle_recipe(self) -> bool:
        return (
            self.kind == SidecarKind.SUBTITLE.value
            and self.codec == "srt"
            and self.source == "generated_srt"
            and self.encoding == "utf8"
            and self.timing_profile == "normal"
        )
```

When iterating declared subtitles, pass the raw fields and render the path with
`codec=codec`.

Update `asset_path_safety.py`, `sidecar_target.py`, and `timeline_lifecycle.py`
callers to pass codec when they rerender declared sidecar paths.

In `sidecar_target.py`, reject mutating timeline operations:

```python
@dataclass(frozen=True, slots=True)
class _SidecarProjectionRow:
    kind: str
    language: str | None
    renderer_derived: bool
    codec: str = "srt"
    source: str = "generated_srt"
    encoding: str = "utf8"
    timing_profile: str = "normal"

    @property
    def uses_default_subtitle_recipe(self) -> bool:
        return (
            self.kind == SidecarKind.SUBTITLE.value
            and self.codec == "srt"
            and self.source == "generated_srt"
            and self.encoding == "utf8"
            and self.timing_profile == "normal"
        )


def _reject_non_default_subtitle_recipe(
    *,
    event: Mapping[str, object],
    entry: _SidecarProjectionRow,
    reporter: Reporter,
    loc: _Loc,
) -> None:
    if entry.kind != SidecarKind.SUBTITLE.value or entry.uses_default_subtitle_recipe:
        return
    reporter.error(
        code=E_MATERIALIZE_UNSUPPORTED,
        message=f"{event.get('action')} does not support non-default subtitle recipes",
        loc=loc,
    )
```

Call it for `update_sidecar` and `embed_subtitle` after resolving the target
projection row.
Seed the row from `DeclaredSidecar` so hierarchy-projected declared sidecars
retain their codec/source/encoding/timing metadata.

- [x] **Step 5: Implement subtitle materialize matrix validation**

In `materialize_media_matrix.py`, add constants:

```python
_SRT_ENCODINGS = frozenset({"utf8", "utf8_bom", "utf16_le", "iso_8859_1"})
_ASS_ENCODINGS = frozenset({"utf8", "utf8_bom"})
_SUBTITLE_MATRIX = {
    ("srt", "generated_srt"): _SRT_ENCODINGS,
    ("ass", "styled_ass"): _ASS_ENCODINGS,
    ("ssa", "styled_ass"): _ASS_ENCODINGS,
}
_SUBTITLE_TIMING_PROFILES = frozenset({"normal", "overlap", "out_of_range"})
```

Add `_check_subtitles(asset, asset_loc, reporter)` and call it for movie/episode
video assets that are not WebM/resolution-switch:

```python
def _check_subtitles(
    *,
    asset: Mapping[str, object],
    asset_loc: _Loc,
    reporter: Reporter,
) -> None:
    for index, raw_sub in enumerate(_as_list(asset.get("subtitles")) or []):
        sub = _as_mapping(raw_sub)
        if sub is None:
            continue
        loc = (*asset_loc, "subtitles", index)
        codec = sub.get("codec")
        source = sub.get("source", "generated_srt")
        encoding = sub.get("encoding", "utf8")
        timing = sub.get("timing_profile", "normal")
        if isinstance(timing, str) and timing not in _SUBTITLE_TIMING_PROFILES:
            reporter.error(
                code=E_MATERIALIZE_UNSUPPORTED,
                message="unsupported subtitle timing_profile",
                loc=(*loc, "timing_profile"),
            )
        if not isinstance(codec, str) or not isinstance(source, str):
            continue
        supported_encodings = _SUBTITLE_MATRIX.get((codec, source))
        if supported_encodings is None:
            reporter.error(
                code=E_MATERIALIZE_UNSUPPORTED,
                message="unsupported subtitle codec/source recipe combination",
                loc=(*loc, "source"),
            )
            continue
        if isinstance(encoding, str) and encoding not in supported_encodings:
            reporter.error(
                code=E_MATERIALIZE_UNSUPPORTED,
                message="unsupported subtitle encoding for codec/source recipe",
                loc=(*loc, "encoding"),
            )
```

- [x] **Step 6: Run green tests and commit**

Run:

```bash
uv run pytest --no-cov tests/validation/rules/test_materialize_media_matrix.py tests/validation/rules/test_sidecar_target.py tests/validation/rules/test_timeline_lifecycle.py -q
uv run ruff check src/chaos_librarian/validation tests/validation/rules
```

Commit:

```bash
git add src/chaos_librarian/validation tests/validation
git commit -m "Validate subtitle recipe matrix"
```

Run one adversarial review pass on the validation diff before continuing.

---

### Task 3: Subtitle Recipe Rendering and Preflight

**Files:**
- Create: `src/chaos_librarian/materializer/tooling/subtitles.py`
- Modify: `src/chaos_librarian/materializer/preflight.py`
- Test: `tests/materializer/test_subtitle_recipes.py`
- Test: `tests/materializer/test_preflight.py`

- [x] **Step 1: Write failing pure recipe tests**

Create `tests/materializer/test_subtitle_recipes.py`:

```python
from chaos_librarian.contract.scenario import (
    SubtitleCodec,
    SubtitleEncoding,
    SubtitleSource,
    SubtitleTimingProfile,
)
from chaos_librarian.materializer.tooling.subtitles import subtitle_payload_bytes


def test_srt_utf8_bom_payload_starts_with_bom() -> None:
    body = subtitle_payload_bytes(
        codec=SubtitleCodec.SRT,
        source=SubtitleSource.GENERATED_SRT,
        encoding=SubtitleEncoding.UTF8_BOM,
        timing_profile=SubtitleTimingProfile.NORMAL,
        language="eng",
        duration_s=2.0,
        seed=42,
    )

    assert body.startswith(b"\xef\xbb\xbf")
    assert b"00:00:02,000" in body


def test_srt_utf16_le_payload_starts_with_bom() -> None:
    body = subtitle_payload_bytes(
        codec=SubtitleCodec.SRT,
        source=SubtitleSource.GENERATED_SRT,
        encoding=SubtitleEncoding.UTF16_LE,
        timing_profile=SubtitleTimingProfile.NORMAL,
        language="eng",
        duration_s=2.0,
        seed=42,
    )

    assert body.startswith(b"\xff\xfe")
    assert "chaos-librarian".encode("utf-16-le") in body


def test_srt_iso_8859_1_payload_is_latin1() -> None:
    body = subtitle_payload_bytes(
        codec=SubtitleCodec.SRT,
        source=SubtitleSource.GENERATED_SRT,
        encoding=SubtitleEncoding.ISO_8859_1,
        timing_profile=SubtitleTimingProfile.NORMAL,
        language="fra",
        duration_s=2.0,
        seed=42,
    )

    assert body.decode("iso-8859-1").startswith("1\n")


def test_ass_payload_contains_style_and_position_tags() -> None:
    body = subtitle_payload_bytes(
        codec=SubtitleCodec.ASS,
        source=SubtitleSource.STYLED_ASS,
        encoding=SubtitleEncoding.UTF8,
        timing_profile=SubtitleTimingProfile.OVERLAP,
        language="jpn",
        duration_s=2.0,
        seed=42,
    ).decode("utf-8")

    assert "[V4+ Styles]" in body
    assert "Style: ChaosDefault" in body
    assert r"{\pos(" in body
    assert body.count("Dialogue:") == 2


def test_ssa_payload_uses_v4_styles_section() -> None:
    body = subtitle_payload_bytes(
        codec=SubtitleCodec.SSA,
        source=SubtitleSource.STYLED_ASS,
        encoding=SubtitleEncoding.UTF8_BOM,
        timing_profile=SubtitleTimingProfile.OUT_OF_RANGE,
        language="spa",
        duration_s=1.0,
        seed=42,
    )

    decoded = body.decode("utf-8-sig")
    assert "[V4 Styles]" in decoded
    assert "0:00:02.00" in decoded
```

- [x] **Step 2: Write failing preflight tests**

Add to `tests/materializer/test_preflight.py`:

```python
def test_preflight_accepts_supported_subtitle_recipes() -> None:
    preflight_asset(
        parent_kind=ParentKind.MOVIE,
        video=_video(),
        audios=[_audio()],
        subtitles=[
            SubtitleTrack(codec="ass", source="styled_ass", language="jpn", mode="sidecar"),
            SubtitleTrack(
                codec="srt",
                language="eng",
                mode="sidecar",
                encoding="utf16_le",
                timing_profile="overlap",
            ),
        ],
        container="mkv",
    )


def test_preflight_rejects_ass_utf16_encoding() -> None:
    with pytest.raises(UnsupportedMaterializationError) as exc:
        preflight_asset(
            parent_kind=ParentKind.MOVIE,
            video=_video(),
            audios=[],
            subtitles=[
                SubtitleTrack(
                    codec="ass",
                    source="styled_ass",
                    language="jpn",
                    mode="sidecar",
                    encoding="utf16_le",
                )
            ],
            container="mkv",
        )

    assert exc.value.field == "subtitle[0].encoding"
```

- [x] **Step 3: Run tests to verify red**

Run:

```bash
uv run pytest --no-cov \
  tests/materializer/test_subtitle_recipes.py \
  tests/materializer/test_preflight.py::test_preflight_accepts_supported_subtitle_recipes \
  tests/materializer/test_preflight.py::test_preflight_rejects_ass_utf16_encoding \
  -q
```

Expected: missing module/function and stale preflight matrix failures.

- [x] **Step 4: Implement pure subtitle renderer**

Create `src/chaos_librarian/materializer/tooling/subtitles.py`:

```python
from __future__ import annotations

from chaos_librarian.contract.scenario import (
    SubtitleCodec,
    SubtitleEncoding,
    SubtitleSource,
    SubtitleTimingProfile,
)
from chaos_librarian.materializer.tooling.recipes import _srt_timestamp


def subtitle_payload_bytes(
    *,
    codec: SubtitleCodec,
    source: SubtitleSource,
    encoding: SubtitleEncoding,
    timing_profile: SubtitleTimingProfile,
    language: str,
    duration_s: float,
    seed: int,
) -> bytes:
    text = _subtitle_text(
        codec=codec,
        source=source,
        timing_profile=timing_profile,
        language=language,
        duration_s=duration_s,
        seed=seed,
    )
    return _encode_text(text, encoding=encoding)
```

Implement private helpers:

- `_subtitle_text(...)` dispatches SRT vs ASS/SSA and raises `UnsupportedMaterializationError` for impossible combinations.
- `_srt_text(...)` emits one normal cue, two overlapping cues, or one out-of-range cue.
- `_ass_text(..., codec)` emits ASS/SSA sections and `Dialogue:` rows with deterministic `\pos(x,y)` tags.
- `_encode_text(...)` returns UTF-8, UTF-8 BOM, UTF-16 LE BOM, or ISO-8859-1 bytes.

Keep function bodies under 100 lines. Do not move `srt_payload`; existing tests import it from `recipes.py`.

- [x] **Step 5: Implement preflight matrix**

In `preflight.py`, replace `_preflight_subtitles` with matrix checks mirroring validation:

```python
_SRT_SUBTITLE_ENCODINGS = frozenset(
    {
        SubtitleEncoding.UTF8,
        SubtitleEncoding.UTF8_BOM,
        SubtitleEncoding.UTF16_LE,
        SubtitleEncoding.ISO_8859_1,
    }
)
_ASS_SUBTITLE_ENCODINGS = frozenset({SubtitleEncoding.UTF8, SubtitleEncoding.UTF8_BOM})
_SUBTITLE_RECIPE_MATRIX = {
    (SubtitleCodec.SRT, SubtitleSource.GENERATED_SRT): _SRT_SUBTITLE_ENCODINGS,
    (SubtitleCodec.ASS, SubtitleSource.STYLED_ASS): _ASS_SUBTITLE_ENCODINGS,
    (SubtitleCodec.SSA, SubtitleSource.STYLED_ASS): _ASS_SUBTITLE_ENCODINGS,
}
```

For each subtitle:

- Reject `mode is not SubtitleMode.SIDECAR`.
- Look up `(sub.codec, sub.source)`.
- Reject missing pair with field `subtitle[index].source`.
- Reject unsupported encoding with field `subtitle[index].encoding`.

- [x] **Step 6: Run green tests and commit**

Run:

```bash
uv run pytest --no-cov tests/materializer/test_subtitle_recipes.py tests/materializer/test_preflight.py -q
uv run ruff check src/chaos_librarian/materializer tests/materializer/test_subtitle_recipes.py tests/materializer/test_preflight.py
uv run ty check src tests/materializer
```

Commit:

```bash
git add src/chaos_librarian/materializer tests/materializer/test_subtitle_recipes.py tests/materializer/test_preflight.py
git commit -m "Add subtitle recipe renderers"
```

Run one adversarial review pass on the renderer/preflight diff before continuing.

---

### Task 4: Materialize Declared Subtitle Recipe Bytes

**Files:**
- Modify: `src/chaos_librarian/materializer/synthesis.py`
- Modify: `src/chaos_librarian/materializer/phase_b/sidecar_bytes.py`
- Modify: `src/chaos_librarian/materializer/phase_b/media.py`
- Test: `tests/materializer/test_synthesis.py`
- Test: `tests/materializer/test_sidecar_bytes.py`
- Test: `tests/materializer/test_media.py`

- [x] **Step 1: Write failing synthesis test**

Add to `tests/materializer/test_synthesis.py`:

```python
def test_materialize_one_asset_writes_multiple_subtitle_recipe_sidecars(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    asset = Asset(
        id="asset_subs",
        role="main",
        container="mkv",
        duration_seconds=2.0,
        video=VideoTrack(source=VideoSource.COLOR_BARS, codec="h264", resolution="sd"),
        subtitles=(
            SubtitleTrack(codec="srt", language="eng", mode="sidecar", encoding="utf8_bom"),
            SubtitleTrack(
                codec="ass",
                source="styled_ass",
                language="jpn",
                mode="sidecar",
                timing_profile="overlap",
            ),
        ),
    )
    output_path = tmp_path / "run" / "library" / "r" / "Movie.mkv"
    _patch_successful_ffmpeg(monkeypatch, output_path)

    result = materialize_one_asset(
        asset,
        139,
        tmp_path / "run",
        _caps(),
        0,
        rendered_relative_path="r/Movie.mkv",
    )

    srt_path = tmp_path / "run" / "library" / "r" / "Movie.eng.srt"
    ass_path = tmp_path / "run" / "library" / "r" / "Movie.jpn.ass"
    assert srt_path.read_bytes().startswith(b"\xef\xbb\xbf")
    assert b"[V4+ Styles]" in ass_path.read_bytes()
    assert result.sidecar_hashes[(asset.id, "eng")] == _sha256(srt_path.read_bytes())
    assert result.sidecar_hashes[(asset.id, "jpn")] == _sha256(ass_path.read_bytes())
```

Add a small `_sha256(data: bytes) -> str` helper in the test file if one does
not exist.

- [x] **Step 2: Write failing phase-B default behavior tests**

In `tests/materializer/test_sidecar_bytes.py`, keep existing assertions and add:

```python
def test_regenerate_sidecar_subtitle_remains_default_utf8_srt() -> None:
    bytes_, argv = regenerate_sidecar(
        kind=SidecarKind.SUBTITLE,
        language="eng",
        sidecar_id="sidecar_0001",
        resolved_seed=42,
        event_id="ev_us_001",
        duration_s=1.0,
    )

    assert argv is None
    assert bytes_ is not None
    assert bytes_.startswith(b"1\n")
    assert b"[Script Info]" not in bytes_
```

- [x] **Step 3: Run tests to verify red**

Run:

```bash
uv run pytest --no-cov \
  tests/materializer/test_synthesis.py::test_materialize_one_asset_writes_multiple_subtitle_recipe_sidecars \
  tests/materializer/test_sidecar_bytes.py::test_regenerate_sidecar_subtitle_remains_default_utf8_srt \
  -q
```

Expected: ASS path missing or SRT BOM missing before implementation.

- [x] **Step 4: Implement synthesis byte writing**

In `synthesis.py`, import `subtitle_payload_bytes`. Change declared sidecar
writing:

```python
sidecar_path = library_dir / render_declared_sidecar_path(
    rendered_relative_path,
    sub.language,
    codec=sub.codec.value,
)
body = subtitle_payload_bytes(
    codec=sub.codec,
    source=sub.source,
    encoding=sub.encoding,
    timing_profile=sub.timing_profile,
    language=sub.language,
    duration_s=asset.duration_seconds,
    seed=seed,
)
sidecar_path.write_bytes(body)
sidecar_hashes[(asset.id, sub.language)] = (
    "sha256:" + hashlib.sha256(body).hexdigest()
)
```

In phase-B subtitle creation/update code, keep default generated SRT behavior but
switch to explicit `subtitle_payload_bytes(...)` with SRT/UTF8/NORMAL where it
reduces duplication. Do not add timeline recipe fields.

- [x] **Step 5: Run green materializer tests and commit**

Run:

```bash
uv run pytest --no-cov tests/materializer/test_synthesis.py tests/materializer/test_sidecar_bytes.py tests/materializer/test_media.py -q
uv run ruff check src/chaos_librarian/materializer tests/materializer
uv run ty check src tests/materializer
```

Commit:

```bash
git add src/chaos_librarian/materializer tests/materializer
git commit -m "Materialize subtitle recipe sidecars"
```

Run one adversarial review pass on the materializer diff before continuing.

---

### Task 5: Schemas, Fixtures, Docs, and Regression Corpus

**Files:**
- Modify: `src/chaos_librarian/contract/__init__.py`
- Modify: `src/chaos_librarian/contract/scenario.py`
- Modify: `docs/contract/schema-reference.md`
- Modify: `schemas/scenario.schema.json`
- Modify: `tests/fixtures/scenarios/**/*.yaml`
- Add invalid fixtures for unsupported subtitle recipe combinations.
- Test: `tests/contract/test_schema_export.py`
- Test: `tests/validation/test_invalid_corpus.py`
- Test: `tests/contract/test_sample_scenarios.py`

- [x] **Step 1: Add invalid corpus fixtures**

Add:

- `tests/fixtures/scenarios/invalid/subtitle-styled-ass-srt.yaml`
- `tests/fixtures/scenarios/invalid/subtitle-ass-utf16.yaml`
- `tests/fixtures/scenarios/invalid/subtitle-update-nondefault.yaml`
- `tests/fixtures/scenarios/invalid/subtitle-embed-nondefault.yaml`

Each file must start with:

```yaml
# expected: E_MATERIALIZE_UNSUPPORTED
```

Use a minimal movie scenario at `schema_version: 23`. The first two fixtures
exercise matrix rejection; the last two declare an ASS sidecar and then target
its `.ass` path with `update_sidecar` or `embed_subtitle`.

- [x] **Step 2: Update schema-version snippets**

Run:

```bash
rg --files tests src -g '*.py' -g '*.yaml' | xargs perl -0pi -e 's/schema_version: 22/schema_version: 23/g; s/schema_version=22/schema_version=23/g; s/"schema_version": 22/"schema_version": 23/g'
```

Manually review the diff and restore any historical version assertions that
must stay old. Do not edit generated schema files by hand.

- [x] **Step 3: Regenerate schemas and update docs**

Run:

```bash
uv run python -m chaos_librarian.schema_export --write
```

Update `docs/contract/schema-reference.md`:

- Current scenario version: `23`
- Add before Scenario v22:

```markdown
Scenario v23 adds explicit sidecar subtitle codec, encoding, and timing recipe
fields. Declared subtitle sidecars can now generate UTF-8/BOM, UTF-16 LE,
ISO-8859-1 SRT, and styled ASS/SSA parser-surface fixtures.
```

- [x] **Step 4: Run schema and corpus verification**

Run:

```bash
uv run python -m chaos_librarian.schema_export --check
uv run pytest --no-cov \
  tests/contract/test_schema_export.py \
  tests/contract/test_contract_constants.py \
  tests/contract/test_sample_scenarios.py \
  tests/validation/test_invalid_corpus.py \
  -q
uv run ruff check src tests
```

- [x] **Step 5: Commit**

```bash
git add docs/contract/schema-reference.md schemas tests src
git commit -m "Regenerate schemas for subtitle recipes"
```

Run one adversarial review pass on the schema/docs/fixtures diff before
continuing.

---

### Task 6: Final Review, Simplification, PR, and Merge

**Files:**
- Entire branch diff against `origin/main`

- [ ] **Step 1: Run adversarial code review**

Review:

```bash
git diff origin/main...HEAD
```

Address material findings. Run no more than three adversarial code review
passes for this implementation cycle.

- [ ] **Step 2: Run simplification review**

Use the simplification-review workflow on the branch diff. Address only
simplifications that reduce risk without widening scope.

- [ ] **Step 3: Final verification**

Run:

```bash
uv run pytest --no-cov -q
uv run ruff check .
uv run ruff format --check .
uv run python -m chaos_librarian.schema_export --check
uv run ty check src tests
prek run --all-files
```

- [ ] **Step 4: Push and open PR**

```bash
git status --short --branch
git push -u origin feat/issue-139-subtitle-recipes
gh pr create --base main --head feat/issue-139-subtitle-recipes \
  --title "Add subtitle recipe variants" \
  --body "Closes #139"
```

Include verification commands and review notes in the PR body.

- [ ] **Step 5: Monitor, merge, and confirm closure**

```bash
gh pr checks <PR_NUMBER> --watch --interval 10
gh pr merge <PR_NUMBER> --merge --delete-branch --repo randomparity/chaos-librarian
gh issue view 139 --repo randomparity/chaos-librarian --json state,closedAt,url
```

Expected: PR merged, issue #139 closed.
