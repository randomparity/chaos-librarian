# Issue 137 Chapters And Cover Art Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic embedded chapters and MP4 attached-picture cover art
to static materialization.

**Architecture:** Add optional asset-level scenario recipe models, carry the new
probe facts through manifest/report/observed-state contracts, validate the small
supported matrix before subprocess work, and extend Phase-A FFmpeg muxing with
temporary chapter metadata and cover-art PNG inputs. Content-source evidence
records the selected recipes so materialize/run replay bundles remain auditable.

**Tech Stack:** Pydantic v2 contracts, validation rules, FFmpeg/ffprobe, pytest,
ruff, ty, checked-in JSON Schema artifacts.

---

## File Map

- `src/chaos_librarian/contract/scenario.py`: add embedded chapter and cover-art
  recipe models/enums on `Asset`, bump `Scenario`.
- `src/chaos_librarian/contract/manifest.py`: add `ProbedChapter`,
  `ProbedMedia.chapters`, and `ProbedStream.attached_pic`, bump `Manifest`.
- `src/chaos_librarian/contract/content_sources.py`: add `chapters` and
  `cover_art` evidence kinds and optional recipe fields.
- `src/chaos_librarian/contract/materialization.py`: bump `MaterializationReport`.
- `src/chaos_librarian/contract/replay_bundle.py`: bump replay bundle.
- `src/chaos_librarian/contract/reports.py`: bump `AssetReport`.
- `src/chaos_librarian/contract/observed_state.py`: bump `ObservedState`.
- `src/chaos_librarian/contract/__init__.py`: bump schema constants.
- `src/chaos_librarian/materializer/tooling/probe.py`: parse chapters and
  attached-picture disposition.
- `src/chaos_librarian/adapter/probe.py`: compare chapters and attached-picture
  fields.
- `src/chaos_librarian/validation/rules/materialize_media_matrix.py`: reject
  unsupported chapter/cover-art combinations.
- `src/chaos_librarian/materializer/tooling/ffmpeg.py`: add optional chapter and
  cover-art inputs to video command building.
- `src/chaos_librarian/materializer/content_sources.py`: add deterministic
  chapter/cover-art evidence helpers.
- `src/chaos_librarian/materializer/synthesis.py`: prepare temp metadata/cover
  inputs, run cover-art prelude, and thread evidence.
- `docs/contract/schema-reference.md`: update contract version table and notes.
- `schemas/*.schema.json`: regenerate affected schema artifacts.

## Task 1: Contract And Probe Shape

**Files:**
- Modify: `src/chaos_librarian/contract/scenario.py`
- Modify: `src/chaos_librarian/contract/manifest.py`
- Modify: `src/chaos_librarian/contract/content_sources.py`
- Modify: `src/chaos_librarian/contract/materialization.py`
- Modify: `src/chaos_librarian/contract/replay_bundle.py`
- Modify: `src/chaos_librarian/contract/reports.py`
- Modify: `src/chaos_librarian/contract/observed_state.py`
- Modify: `src/chaos_librarian/contract/__init__.py`
- Modify: `src/chaos_librarian/materializer/tooling/probe.py`
- Modify: `src/chaos_librarian/adapter/probe.py`
- Test: `tests/contract/test_scenario.py`
- Test: `tests/contract/test_manifest.py`
- Test: `tests/contract/test_contract_constants.py`
- Test: `tests/materializer/test_probe.py`
- Test: `tests/adapter/test_probe.py`

- [ ] **Step 1: Write failing contract and probe tests**

Add scenario tests for the new asset fields:

```python
def test_embedded_chapters_and_cover_art_asset_round_trip() -> None:
    payload = _base_payload()
    asset = _video_asset_payload("asset_embedded_metadata")
    asset["container"] = "mp4"
    asset["embedded_chapters"] = {"count": 3, "title_prefix": "Scene"}
    asset["embedded_cover_art"] = {
        "source": "solid_color",
        "image_format": "png",
        "resolution": "square_320",
    }
    payload["movies"] = [
        {
            "id": "movie_embedded_metadata",
            "title": "Embedded Metadata",
            "layout": "movie_flat",
            "variants": [_variant_payload(asset)],
        }
    ]

    scenario = Scenario.model_validate(payload)
    asset_model = scenario.movies[0].variants[0].bundle.assets[0]

    assert asset_model.embedded_chapters is not None
    assert asset_model.embedded_chapters.count == 3
    assert asset_model.embedded_chapters.title_prefix == "Scene"
    assert asset_model.embedded_cover_art is not None
    assert asset_model.embedded_cover_art.source.value == "solid_color"
```

Add a manifest probe round-trip test:

```python
media = ProbedMedia(
    container="mov,mp4,m4a,3gp,3g2,mj2",
    duration_seconds=2.0,
    size_bytes=1024,
    streams=[
        ProbedStream(
            kind=StreamKind.VIDEO,
            codec="png",
            width=320,
            height=320,
            attached_pic=True,
        )
    ],
    chapters=[ProbedChapter(index=0, start_ms=0, end_ms=1000, title="Scene 01 abc123")],
)
loaded = ProbedMedia.model_validate_json(media.model_dump_json())
assert loaded.chapters[0].title == "Scene 01 abc123"
assert loaded.streams[0].attached_pic is True
```

Add probe parser tests that mock ffprobe JSON containing `chapters` and video
`disposition.attached_pic = 1`, and assert `probe_file()` includes
`-show_chapters` in the subprocess argv.

Add adapter comparison tests for:

```python
("chapters.length", 1, 0)
("chapters.0.title", "Scene 01 abc123", "Scene 01 def456")
("streams.0.attached_pic", True, False)
```

Update constant expectations to:

```python
assert SCENARIO_SCHEMA_VERSION == 21
assert MANIFEST_SCHEMA_VERSION == 9
assert REPLAY_BUNDLE_SCHEMA_VERSION == 11
assert ASSET_REPORT_SCHEMA_VERSION == 9
assert OBSERVED_STATE_SCHEMA_VERSION == 4
assert MATERIALIZATION_SCHEMA_VERSION == 14
```

- [ ] **Step 2: Run tests to verify RED**

```bash
uv run pytest --no-cov \
  tests/contract/test_scenario.py \
  tests/contract/test_manifest.py \
  tests/contract/test_contract_constants.py \
  tests/materializer/test_probe.py \
  tests/adapter/test_probe.py -q
```

Expected: failures for missing fields/classes, old schema versions, and missing
probe parsing.

- [ ] **Step 3: Implement contract and probe shape**

Add to `scenario.py`:

```python
class CoverArtSource(enum.StrEnum):
    SOLID_COLOR = "solid_color"


class CoverArtImageFormat(enum.StrEnum):
    PNG = "png"


class CoverArtResolution(enum.StrEnum):
    SQUARE_320 = "square_320"


class EmbeddedChapters(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    count: int = Field(ge=1, le=20)
    title_prefix: str = Field(default="Chapter", min_length=1, max_length=64)


class EmbeddedCoverArt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source: CoverArtSource = CoverArtSource.SOLID_COLOR
    image_format: CoverArtImageFormat = CoverArtImageFormat.PNG
    resolution: CoverArtResolution = CoverArtResolution.SQUARE_320
```

Add to `Asset`:

```python
embedded_chapters: EmbeddedChapters | None = None
embedded_cover_art: EmbeddedCoverArt | None = None
```

Add to `manifest.py`:

```python
class ProbedChapter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=0)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    title: str | None = None


attached_pic: bool | None = None  # video-only
chapters: list[ProbedChapter] = Field(default_factory=list)
```

Add to `ContentTrackKind`:

```python
CHAPTERS = "chapters"
COVER_ART = "cover_art"
```

Add optional fields to `ContentSourceEvidence`:

```python
chapter_count: int | None = Field(default=None, ge=1)
chapter_title_prefix: str | None = None
cover_art_image_format: CoverArtImageFormat | None = None
cover_art_resolution: CoverArtResolution | None = None
cover_art_color: str | None = Field(default=None, pattern=r"^#[0-9a-f]{6}$")
```

Update all schema constants and direct `Literal[...]` annotations listed in the
test step.

Update `probe.py` to include `-show_chapters`, parse `disposition.attached_pic`,
and map chapters into `ProbedChapter` using ffprobe integer `start`/`end` values
when `time_base == "1/1000"`, otherwise derive milliseconds from
`start_time`/`end_time`.

Update `adapter/probe.py` to compare `attached_pic` in `_compare_stream()` and
add a `_compare_chapters()` helper called by `compare_probed_media()`.

- [ ] **Step 4: Run tests to verify GREEN**

```bash
uv run pytest --no-cov \
  tests/contract/test_scenario.py \
  tests/contract/test_manifest.py \
  tests/contract/test_contract_constants.py \
  tests/materializer/test_probe.py \
  tests/adapter/test_probe.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/chaos_librarian/contract src/chaos_librarian/materializer/tooling/probe.py \
  src/chaos_librarian/adapter/probe.py tests/contract tests/materializer/test_probe.py \
  tests/adapter/test_probe.py
git commit -m "Add embedded metadata contract shapes"
```

## Task 2: Validation Matrix

**Files:**
- Modify: `src/chaos_librarian/validation/rules/materialize_media_matrix.py`
- Modify: `tests/validation/rules/test_materialize_media_matrix.py`
- Create: `tests/fixtures/scenarios/invalid/embedded-chapters-audio-track.yaml`
- Create: `tests/fixtures/scenarios/invalid/embedded-cover-art-mkv.yaml`
- Test: `tests/validation/rules/test_materialize_media_matrix.py`
- Test: `tests/validation/test_invalid_corpus.py`

- [ ] **Step 1: Write failing validation tests**

Extend `_write_movie_scenario()` with:

```python
embedded_chapters: bool = False,
embedded_cover_art: bool = False,
```

Render blocks:

```python
chapters_block = (
    "              embedded_chapters:\n"
    "                count: 2\n"
    "                title_prefix: Scene\n"
    if embedded_chapters
    else ""
)
cover_block = (
    "              embedded_cover_art:\n"
    "                source: solid_color\n"
    "                image_format: png\n"
    "                resolution: square_320\n"
    if embedded_cover_art
    else ""
)
```

Add tests:

```python
def test_embedded_chapters_validate_for_mp4_and_mkv(tmp_path: Path) -> None:
    for container in ("mp4", "mkv"):
        scenario = tmp_path / f"chapters-{container}.yaml"
        _write_movie_scenario(scenario, container=container, embedded_chapters=True)
        report = run_validation(prepare_run_input(scenario))
        assert report.ok is True


def test_embedded_cover_art_validates_for_mp4(tmp_path: Path) -> None:
    scenario = tmp_path / "cover-art-mp4.yaml"
    _write_movie_scenario(scenario, container="mp4", embedded_cover_art=True)
    report = run_validation(prepare_run_input(scenario))
    assert report.ok is True


def test_embedded_cover_art_rejects_mkv(tmp_path: Path) -> None:
    scenario = tmp_path / "cover-art-mkv.yaml"
    _write_movie_scenario(scenario, container="mkv", embedded_cover_art=True)
    path = _first_materialize_issue_path(scenario)
    assert path.endswith(".assets[0].embedded_cover_art")
```

Add one test for `embedded_chapters.count` exceeding rounded duration
milliseconds and one for resolution-switch rejecting either field.

Add invalid fixtures with first-line markers. For
`embedded-cover-art-mkv.yaml`:

```yaml
# expected: E_MATERIALIZE_UNSUPPORTED
schema_version: 21
scenario_id: invalid-embedded-cover-art-mkv
seed: 137
duration_scale: short
library: {roots: [{id: root_main, path: library}]}
movies:
  - id: movie_bad
    title: Bad Cover Art
    layout: movie_flat
    variants:
      - id: variant_bad
        label: mkv
        bundle:
          id: bundle_bad
          assets:
            - id: asset_bad
              role: main
              container: mkv
              duration_seconds: 1.0
              embedded_cover_art:
                source: solid_color
                image_format: png
                resolution: square_320
              video: {source: color_bars, codec: h264, resolution: sd}
              audio: [{source: sine, codec: aac, channels: stereo, language: eng}]
series: []
artists: []
timeline: []
```

For `embedded-chapters-audio-track.yaml`:

```yaml
# expected: E_MATERIALIZE_UNSUPPORTED
schema_version: 21
scenario_id: invalid-embedded-chapters-audio-track
seed: 137
duration_scale: short
library: {roots: [{id: root_main, path: library}]}
movies: []
series: []
artists:
  - id: artist_bad
    name: Bad Chapters
    layout: artist_album_flat
    track_naming: track_number_title
    albums:
      - id: album_bad
        title: Bad Album
        discs:
          - id: disc_bad
            disc_number: 1
            tracks:
              - id: track_bad
                track_number: 1
                title: Bad Track
                variants:
                  - id: variant_bad
                    label: flac
                    bundle:
                      id: bundle_bad
                      assets:
                        - id: asset_bad
                          role: main
                          container: flac
                          duration_seconds: 1.0
                          embedded_chapters: {count: 2, title_prefix: Scene}
                          audio:
                            - source: sine
                              codec: flac
                              channels: stereo
                              language: eng
timeline: []
```

- [ ] **Step 2: Run tests to verify RED**

```bash
uv run pytest --no-cov \
  tests/validation/rules/test_materialize_media_matrix.py \
  tests/validation/test_invalid_corpus.py -q
```

Expected: failures for accepted unsupported combinations and fixture schema
version mismatch until implementation lands.

- [ ] **Step 3: Implement validation**

In `_check_video_asset()`, call a new helper before normal media checks:

```python
_check_embedded_metadata(asset=asset, asset_loc=asset_loc, reporter=reporter)
```

Implement separate video and track checks so audio-only assets reject the fields
unconditionally:

```python
def _check_video_embedded_metadata(
    *,
    asset: Mapping[str, object],
    asset_loc: _Loc,
    reporter: Reporter,
) -> None:
    container = asset.get("container")
    chapters = _as_mapping(asset.get("embedded_chapters"))
    cover_art = _as_mapping(asset.get("embedded_cover_art"))
    if chapters is not None:
        if container not in {"mp4", "mkv"}:
            reporter.error(
                code=E_MATERIALIZE_UNSUPPORTED,
                message="embedded_chapters is only supported for mp4 and mkv video assets",
                loc=(*asset_loc, "embedded_chapters"),
            )
        _check_chapter_duration(
            asset=asset,
            chapters=chapters,
            asset_loc=asset_loc,
            reporter=reporter,
        )
    if cover_art is not None and container != "mp4":
        reporter.error(
            code=E_MATERIALIZE_UNSUPPORTED,
            message="embedded_cover_art is only supported for mp4 video assets",
            loc=(*asset_loc, "embedded_cover_art"),
        )
```

Implement duration validation:

```python
def _check_chapter_duration(
    *,
    asset: Mapping[str, object],
    chapters: Mapping[str, object],
    asset_loc: _Loc,
    reporter: Reporter,
) -> None:
    count = chapters.get("count")
    duration = asset.get("duration_seconds")
    if not isinstance(count, int) or isinstance(count, bool):
        return
    if not isinstance(duration, int | float) or isinstance(duration, bool):
        return
    if count <= round(float(duration) * 1000):
        return
    reporter.error(
        code=E_MATERIALIZE_UNSUPPORTED,
        message="embedded_chapters.count requires at least one millisecond per chapter",
        loc=(*asset_loc, "embedded_chapters", "count"),
    )
```

Implement track and resolution-switch rejection:

```python
def _reject_embedded_metadata_for_asset(
    *,
    asset: Mapping[str, object],
    asset_loc: _Loc,
    reporter: Reporter,
    reason: str,
) -> None:
    for field_name in ("embedded_chapters", "embedded_cover_art"):
        if _as_mapping(asset.get(field_name)) is None:
            continue
        reporter.error(
            code=E_MATERIALIZE_UNSUPPORTED,
            message=f"{field_name} {reason}",
            loc=(*asset_loc, field_name),
        )
```

Call `_reject_embedded_metadata_for_asset()` from `_check_track_asset()` with
`reason="is only supported for video assets"` and from
`_check_resolution_switch_video()` with
`reason="cannot be combined with resolution-switch video materialization"`.

- [ ] **Step 4: Run tests to verify GREEN**

```bash
uv run pytest --no-cov \
  tests/validation/rules/test_materialize_media_matrix.py \
  tests/validation/test_invalid_corpus.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/chaos_librarian/validation/rules/materialize_media_matrix.py \
  tests/validation/rules/test_materialize_media_matrix.py \
  tests/fixtures/scenarios/invalid
git commit -m "Validate embedded chapter and cover art support"
```

## Task 3: FFmpeg And Materialization

**Files:**
- Modify: `src/chaos_librarian/materializer/tooling/ffmpeg.py`
- Modify: `src/chaos_librarian/materializer/content_sources.py`
- Modify: `src/chaos_librarian/materializer/synthesis.py`
- Modify: `tests/materializer/test_ffmpeg_builder.py`
- Modify: `tests/materializer/test_content_sources.py`
- Modify: `tests/materializer/test_synthesis.py`

- [ ] **Step 1: Write failing FFmpeg/materialization tests**

Builder tests:

```python
chapters = FFmpegInput(
    file_path=tmp_path / "chapters.ffmeta",
    extra_flags=("-f", "ffmetadata"),
)
cover = FFmpegInput(file_path=tmp_path / "cover.png")
argv = build_command(
    video=_video(),
    video_input=recipe_color_bars(width=640, height=480, fps=24, duration_s=1.0, seed=1),
    audios=[_audio()],
    audio_inputs=[recipe_sine(channels="stereo", duration_s=1.0, seed=1)],
    output_path=tmp_path / "asset.mp4",
    chapters_input=chapters,
    cover_art_input=cover,
)
map_values = [argv[index + 1] for index, arg in enumerate(argv) if arg == "-map"]
assert map_values == ["0:v:0", "1:a:0", "3:v:0"]
assert argv[argv.index("-map_chapters") + 1] == "2"
assert argv[argv.index("-disposition:v:1") + 1] == "attached_pic"
assert argv.index("-map_metadata", argv.index("-fflags")) < argv.index("-map_chapters")
```

Synthesis tests should monkeypatch `run_ffmpeg` and `build_command` to assert:

- `build_command()` receives non-`None` `chapters_input` and `cover_art_input`.
- `result.prelude_invocations` contains one cover-art generation invocation.
- `result.content_sources` includes `ContentTrackKind.CHAPTERS` and
  `ContentTrackKind.COVER_ART`.
- The chapter metadata temp file contains `[CHAPTER]` blocks and deterministic
  titles.

Content-source tests should assert deterministic evidence:

```python
first = resolve_chapter_source(asset_id="a", seed=1, duration_s=2.0, chapters=chapters)
second = resolve_chapter_source(asset_id="a", seed=1, duration_s=2.0, chapters=chapters)
assert first.evidence.recipe_digest == second.evidence.recipe_digest
assert first.evidence.chapter_count == 2
```

- [ ] **Step 2: Run tests to verify RED**

```bash
uv run pytest --no-cov \
  tests/materializer/test_ffmpeg_builder.py \
  tests/materializer/test_content_sources.py \
  tests/materializer/test_synthesis.py -q
```

Expected: failures for unknown build args, missing helpers, and missing evidence.

- [ ] **Step 3: Implement FFmpeg command support**

Add optional parameters to `build_command()` and `_build_video_command()`:

```python
chapters_input: FFmpegInput | None = None
cover_art_input: FFmpegInput | None = None
```

Reject either parameter for audio-only output with fields `embedded_chapters` and
`embedded_cover_art`.

In `_build_video_command()`, append chapter and cover inputs after audio inputs,
compute their input indexes, and emit:

```python
if cover_art_input is not None:
    argv.extend(["-map", f"{cover_art_index}:v:0"])
argv.extend(["-c:v", VIDEO_ENCODER_BY_CODEC[video.codec], "-preset", "medium"])
argv.extend(_BITEXACT_OUTPUT_FLAGS)
if chapters_input is not None:
    argv.extend(["-map_metadata", str(chapter_index), "-map_chapters", str(chapter_index)])
if cover_art_input is not None:
    argv.extend(["-c:v:1", "png", "-disposition:v:1", "attached_pic"])
```

- [ ] **Step 4: Implement deterministic source helpers**

In `content_sources.py`, add:

```python
@dataclass(frozen=True, slots=True)
class ChapterSourceRequest:
    asset_id: str
    seed: int
    duration_s: float
    count: int
    title_prefix: str


@dataclass(frozen=True, slots=True)
class CoverArtSourceRequest:
    asset_id: str
    seed: int
    image_format: CoverArtImageFormat
    resolution: CoverArtResolution
```

Add `resolve_chapter_source()` returning chapter specs plus evidence, and
`resolve_cover_art_source()` returning color plus evidence. Reuse the existing
digest pattern with a local payload helper rather than routing these through the
video/audio provider protocol.

- [ ] **Step 5: Implement Phase-A preparation**

In `synthesis.py`, add a small private result type:

```python
@dataclass(frozen=True, slots=True)
class _EmbeddedMetadataInputs:
    chapters_input: FFmpegInput | None
    cover_art_input: FFmpegInput | None
    evidence: tuple[ContentSourceEvidence, ...]
    prelude_invocations: tuple[ToolInvocation, ...]
```

Use `TemporaryDirectory` around normal materialization. Write chapter ffmetadata
inside it when requested. For cover art, build and run a prelude command:

```python
[
    "ffmpeg",
    "-hide_banner",
    "-y",
    "-f",
    "lavfi",
    "-i",
    f"color=c={color}:s=320x320",
    "-frames:v",
    "1",
    str(cover_path),
]
```

Pass the prepared inputs to `build_command()`, append prelude invocations to the
result, and include embedded metadata evidence with existing video/audio
evidence. On prelude failure, raise `_tool_failed()` with all available content
sources.

- [ ] **Step 6: Run tests to verify GREEN**

```bash
uv run pytest --no-cov \
  tests/materializer/test_ffmpeg_builder.py \
  tests/materializer/test_content_sources.py \
  tests/materializer/test_synthesis.py -q
```

Expected: pass.

- [ ] **Step 7: Commit**

```bash
git add src/chaos_librarian/materializer tests/materializer
git commit -m "Materialize embedded chapters and cover art"
```

## Task 4: Real Media Smoke, Schemas, And Docs

**Files:**
- Create: `tests/materializer/test_embedded_metadata_real.py`
- Modify: `docs/contract/schema-reference.md`
- Modify: `schemas/*.schema.json`

- [ ] **Step 1: Write real FFmpeg smoke tests**

Create tests that skip only when `ffmpeg` or `ffprobe` is unavailable:

```python
def test_materialize_mp4_embedded_metadata_is_probe_visible(tmp_path: Path) -> None:
    asset = Asset(
        id="asset_embed",
        role="main",
        container="mp4",
        duration_seconds=1.0,
        embedded_chapters=EmbeddedChapters(count=2, title_prefix="Scene"),
        embedded_cover_art=EmbeddedCoverArt(),
        video=VideoTrack(source=VideoSource.COLOR_BARS, codec="h264", resolution="sd"),
        audio=(
            AudioTrack(
                source=AudioSource.SINE,
                codec="aac",
                channels=AudioChannelLayout.STEREO,
                language="eng",
            ),
        ),
    )
    result = materialize_one_asset(
        asset,
        137,
        tmp_path / "run",
        _caps(),
        0,
        rendered_relative_path="r/Embed.mp4",
    )
    assert len(result.probed.chapters) == 2
    assert any(stream.attached_pic is True for stream in result.probed.streams)
```

Add a second real test for MKV chapters without cover art. Define a local
`_caps()` helper in the new file using the same `Capabilities` shape as
`tests/materializer/test_synthesis.py`.

- [ ] **Step 2: Run smoke tests to verify behavior**

```bash
uv run pytest --no-cov tests/materializer/test_embedded_metadata_real.py -q
```

Expected before implementation is RED if the file was created earlier; after
Task 3 it should pass on hosts with FFmpeg/ffprobe and skip only if tools are
missing.

- [ ] **Step 3: Regenerate schemas and update docs**

```bash
uv run python -m chaos_librarian.schema_export --write
```

Update `docs/contract/schema-reference.md` current versions:

```text
scenario 21
manifest 9
replay bundle 11
materialization 14
asset report 9
observed state 4
```

Add a note:

```markdown
Scenario v21 adds `embedded_chapters` and `embedded_cover_art` asset recipes.
Manifest v9, asset-report v9, and observed-state v4 carry probe-visible
chapters and attached-picture stream disposition. Materialization v14 and
replay-bundle v11 carry selected chapter and cover-art recipe evidence.
```

- [ ] **Step 4: Run schema/docs verification**

```bash
uv run python -m chaos_librarian.schema_export --check
uv run pytest --no-cov \
  tests/contract/test_schema_export.py \
  tests/contract/test_contract_constants.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add tests/materializer/test_embedded_metadata_real.py docs/contract/schema-reference.md schemas
git commit -m "Regenerate schemas for embedded metadata"
```

## Task 5: Final Review And Verification

**Files:**
- Review full branch diff.

- [ ] **Step 1: Run focused regression suite**

```bash
uv run pytest --no-cov \
  tests/contract/test_scenario.py \
  tests/contract/test_manifest.py \
  tests/contract/test_contract_constants.py \
  tests/materializer/test_probe.py \
  tests/materializer/test_ffmpeg_builder.py \
  tests/materializer/test_content_sources.py \
  tests/materializer/test_synthesis.py \
  tests/materializer/test_embedded_metadata_real.py \
  tests/adapter/test_probe.py \
  tests/validation/rules/test_materialize_media_matrix.py \
  tests/validation/test_invalid_corpus.py -q
```

Expected: pass, with skips only for missing local FFmpeg/ffprobe in real smoke
tests.

- [ ] **Step 2: Run final gates**

```bash
uv run python -m chaos_librarian.schema_export --check
uv run ruff check .
uv run ruff format --check .
uv run ty check src tests
uv run pytest -q
git diff --check
```

Expected: all commands exit 0.

- [ ] **Step 3: Run adversarial code review**

Review `git diff origin/main...HEAD` for schema drift, unsupported matrix gaps,
FFmpeg argument ordering, temp-file lifetime, and probe comparison regressions.
Address up to three rounds of material findings.

- [ ] **Step 4: Run simplification review**

Review the final diff for unnecessary helpers, duplicated digest code, or
oversized materializer functions. Address the highest-leverage safe
recommendations.

- [ ] **Step 5: Push, PR, monitor, merge, close**

```bash
git push -u origin feat/issue-137-chapters-cover-art
gh pr create --fill --base main --head feat/issue-137-chapters-cover-art
gh pr checks --watch
gh pr merge --squash --delete-branch
gh issue close 137 --comment "Implemented in PR #<number>."
```

Expected: CI passes, PR merges to `main`, and issue #137 is closed.
