# Issue 135 Audio Layouts And Roles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add selected expanded audio channel layouts and explicit audio track roles with probe-visible metadata.

**Architecture:** Extend the scenario contract first, then make recipes produce the requested layout before muxing. The FFmpeg builder writes per-audio-stream metadata in declaration order, and probe/oracle contracts preserve the metadata for adapter comparison.

**Tech Stack:** Python 3.13, Pydantic v2, Typer CLI, FFmpeg/ffprobe, pytest, ruff, ty.

---

### Task 1: Contract And Probe Shape

**Files:**
- Modify: `src/chaos_librarian/contract/scenario.py`
- Modify: `src/chaos_librarian/contract/manifest.py`
- Modify: `src/chaos_librarian/contract/observed_state.py`
- Modify: `src/chaos_librarian/contract/reports.py`
- Modify: `src/chaos_librarian/contract/__init__.py`
- Test: `tests/contract/test_scenario.py`
- Test: `tests/contract/test_manifest.py`
- Test: `tests/contract/test_reports.py`
- Test: `tests/contract/test_contract_constants.py`

- [ ] **Step 1: Write failing scenario contract tests**

Add tests equivalent to:

```python
def test_audio_track_accepts_expanded_channel_layouts_and_roles() -> None:
    track = AudioTrack.model_validate(
        {"codec": "aac", "channels": "lcr", "language": "eng", "role": "commentary"}
    )

    assert track.channels is AudioChannelLayout.LCR
    assert track.role is AudioTrackRole.COMMENTARY


def test_audio_track_role_defaults_to_main() -> None:
    track = AudioTrack.model_validate({"codec": "aac", "channels": "4.0", "language": "eng"})

    assert track.role is AudioTrackRole.MAIN


def test_audio_channel_layout_enum_values() -> None:
    assert AUDIO_CHANNEL_COUNTS_BY_NAME["4.0"] == 4
    assert AUDIO_CHANNEL_COUNTS_BY_NAME["lcr"] == 3
    assert AUDIO_CHANNEL_COUNTS_BY_NAME["6.1"] == 7
    assert AUDIO_FFMPEG_CHANNEL_LAYOUT_BY_NAME["lcr"] == "3.0"
```

Run: `uv run pytest --no-cov tests/contract/test_scenario.py -q`
Expected: FAIL because `AudioTrackRole`, `AudioChannelLayout.LCR`, and layout maps do not exist.

- [ ] **Step 2: Implement scenario enums and constants**

Add:

```python
class AudioTrackRole(enum.StrEnum):
    MAIN = "main"
    COMMENTARY = "commentary"
    ALTERNATE = "alternate"
```

Extend `AudioChannelLayout`, `AUDIO_CHANNEL_COUNTS_BY_NAME`, and add:

```python
AUDIO_FFMPEG_CHANNEL_LAYOUT_BY_NAME: Final[dict[str, str]] = {
    "mono": "mono",
    "stereo": "stereo",
    "2.1": "2.1",
    "4.0": "4.0",
    "lcr": "3.0",
    "5.1": "5.1",
    "6.1": "6.1",
    "7.1": "7.1",
}
AUDIO_CHANNEL_ORDER_BY_NAME: Final[dict[str, tuple[str, ...]]] = {
    "mono": ("FC",),
    "stereo": ("FL", "FR"),
    "2.1": ("FL", "FR", "LFE"),
    "4.0": ("FL", "FR", "FC", "BC"),
    "lcr": ("FL", "FR", "FC"),
    "5.1": ("FL", "FR", "FC", "LFE", "BL", "BR"),
    "6.1": ("FL", "FR", "FC", "LFE", "BC", "SL", "SR"),
    "7.1": ("FL", "FR", "FC", "LFE", "BL", "BR", "SL", "SR"),
}
```

Add `role: AudioTrackRole = AudioTrackRole.MAIN` to `AudioTrack`.

- [ ] **Step 3: Write failing probe-shape tests**

Add `ProbedStream` assertions:

```python
stream = ProbedStream(
    kind=StreamKind.AUDIO,
    codec="aac",
    channels=3,
    channel_layout="3.0",
    title="Commentary",
    role="commentary",
)
assert stream.channel_layout == "3.0"
assert stream.title == "Commentary"
assert stream.role == "commentary"
```

Update constants tests to expect:

```python
assert SCENARIO_SCHEMA_VERSION == 19
assert MANIFEST_SCHEMA_VERSION == 8
assert ASSET_REPORT_SCHEMA_VERSION == 8
assert OBSERVED_STATE_SCHEMA_VERSION == 3
```

Run: `uv run pytest --no-cov tests/contract/test_manifest.py tests/contract/test_contract_constants.py tests/contract/test_reports.py -q`
Expected: FAIL because versions and fields are not bumped yet.

- [ ] **Step 4: Implement probe-shape contract bumps**

Set:

```python
SCENARIO_SCHEMA_VERSION: Final = 19
MANIFEST_SCHEMA_VERSION: Final = 8
ASSET_REPORT_SCHEMA_VERSION: Final = 8
OBSERVED_STATE_SCHEMA_VERSION: Final = 3
```

Change literals:

```python
Scenario.schema_version: Literal[19]
Manifest.schema_version: Literal[8]
AssetReport.schema_version: Literal[8]
ObservedState.schema_version: Literal[3]
```

Add optional `channel_layout`, `title`, and `role` fields to `ProbedStream`.

- [ ] **Step 5: Verify contract task**

Run:

```bash
uv run pytest --no-cov tests/contract/test_scenario.py \
  tests/contract/test_manifest.py \
  tests/contract/test_contract_constants.py \
  tests/contract/test_reports.py -q
```

Expected: PASS.

Commit:

```bash
git add src/chaos_librarian/contract tests/contract
git commit -m "Add audio layout and role contracts"
```

### Task 2: Probe Parser And Adapter Comparison

**Files:**
- Modify: `src/chaos_librarian/materializer/tooling/probe.py`
- Modify: `src/chaos_librarian/adapter/probe.py`
- Test: `tests/materializer/test_probe.py`
- Test: `tests/adapter/test_probe.py`

- [ ] **Step 1: Write failing probe parser tests**

Add test input with audio tags:

```python
probe = {
    "format": {"format_name": "matroska,webm", "duration": "2", "size": "100"},
    "streams": [
        {"codec_type": "video", "codec_name": "h264", "tags": {"handler_name": "VideoHandler"}},
        {
            "codec_type": "audio",
            "codec_name": "aac",
            "channels": 3,
            "channel_layout": "3.0",
            "sample_rate": "48000",
            "tags": {"language": "eng", "title": "Commentary", "ROLE": "commentary"},
        },
    ],
}
```

Assert audio `channel_layout`, `title`, and `role`, and assert the video stream
does not inherit `VideoHandler` as `title`.

Run: `uv run pytest --no-cov tests/materializer/test_probe.py -q`
Expected: FAIL because the parser drops the new fields.

- [ ] **Step 2: Implement probe parser fields**

Add a case-insensitive tag helper:

```python
def _tag_value(blob: dict[str, object], key: str) -> str | None:
    tags = _coerce_blob(blob.get("tags"))
    if tags is None:
        return None
    for tag_key, tag_value in tags.items():
        if tag_key.casefold() == key.casefold():
            return str(tag_value)
    return None
```

For audio streams set:

```python
channel_layout=_opt_str(blob, "channel_layout"),
title=_tag_value(blob, "title") or _tag_value(blob, "handler_name"),
role=_tag_value(blob, "role"),
```

For video streams set `title=_tag_value(blob, "title")` only.

- [ ] **Step 3: Write failing adapter comparison test**

Add:

```python
def test_compare_probed_media_reports_audio_layout_title_and_role_mismatch() -> None:
    expected = _media(streams=[
        ProbedStream(
            kind=StreamKind.AUDIO,
            codec="aac",
            channel_layout="3.0",
            title="Commentary",
            role="commentary",
        )
    ])
    observed = _media(streams=[
        ProbedStream(
            kind=StreamKind.AUDIO,
            codec="aac",
            channel_layout="2.1",
            title="Main Audio",
            role="main",
        )
    ])

    differences = compare_probed_media(expected, observed)

    assert ("streams.0.channel_layout", "3.0", "2.1") in differences
    assert ("streams.0.title", "Commentary", "Main Audio") in differences
    assert ("streams.0.role", "commentary", "main") in differences
```

Run: `uv run pytest --no-cov tests/adapter/test_probe.py -q`
Expected: FAIL because comparison ignores new fields.

- [ ] **Step 4: Implement adapter comparison fields**

Add `channel_layout`, `title`, and `role` to the `_compare_stream` field tuple.

- [ ] **Step 5: Verify parser/comparison task**

Run:

```bash
uv run pytest --no-cov tests/materializer/test_probe.py tests/adapter/test_probe.py -q
```

Expected: PASS.

Commit:

```bash
git add src/chaos_librarian/materializer/tooling/probe.py \
  src/chaos_librarian/adapter/probe.py \
  tests/materializer/test_probe.py tests/adapter/test_probe.py
git commit -m "Parse audio role probe metadata"
```

### Task 3: Audio Recipe Layouts

**Files:**
- Modify: `src/chaos_librarian/materializer/tooling/recipes.py`
- Test: `tests/materializer/test_recipes.py`
- Test: `tests/materializer/test_content_sources.py`

- [ ] **Step 1: Write failing recipe tests**

Add tests asserting generated lavfi strings:

```python
assert "pan=3.0|FL=c0|FR=c0|FC=c0" in recipe_sine(
    channels="lcr", duration_s=1.0, seed=1
).lavfi
assert "anullsrc=channel_layout=6.1" in recipe_silence(
    channels="6.1", duration_s=1.0, seed=1
).lavfi
assert "join=inputs=4:channel_layout=4.0" in recipe_channel_tones(
    channels="4.0", duration_s=1.0, seed=1
).lavfi
assert "pan=4.0" in recipe_noise(
    channels="4.0", duration_s=1.0, seed=1, noise_color=AudioNoiseColor.WHITE
).lavfi
```

Run: `uv run pytest --no-cov tests/materializer/test_recipes.py -q`
Expected: FAIL because existing recipes do not honor the new layouts.

- [ ] **Step 2: Implement layout helpers**

Use contract maps:

```python
def _ffmpeg_layout(channels: str) -> str:
    return AUDIO_FFMPEG_CHANNEL_LAYOUT_BY_NAME[channels]


def _pan_mono_to_layout(lavfi: str, channels: str) -> str:
    order = AUDIO_CHANNEL_ORDER_BY_NAME[channels]
    if len(order) == 1:
        return lavfi
    mappings = "|".join(f"{channel}=c0" for channel in order)
    return f"{lavfi},pan={_ffmpeg_layout(channels)}|{mappings}"
```

Use `join` for `channel_tones`:

```python
maps = "|".join(f"{index}.0-{channel}" for index, channel in enumerate(order))
lavfi = ";".join([*labeled, f"{merge_inputs}join=inputs={count}:channel_layout={layout}:map={maps}"])
```

- [ ] **Step 3: Verify content-source digest still records track indexes**

Add or update a content-source test to request `channels="lcr"` and assert
`track_index == 0` remains present.

Run:

```bash
uv run pytest --no-cov tests/materializer/test_recipes.py tests/materializer/test_content_sources.py -q
```

Expected: PASS.

Commit:

```bash
git add src/chaos_librarian/materializer/tooling/recipes.py \
  tests/materializer/test_recipes.py tests/materializer/test_content_sources.py
git commit -m "Honor declared audio channel layouts"
```

### Task 4: FFmpeg Audio Metadata

**Files:**
- Modify: `src/chaos_librarian/materializer/tooling/ffmpeg.py`
- Test: `tests/materializer/test_ffmpeg_builder.py`
- Test: `tests/materializer/test_audio_only.py`

- [ ] **Step 1: Write failing FFmpeg builder tests**

Add a multiple-audio test:

```python
argv = build_command(
    video=_video(),
    video_input=recipe_color_bars(width=640, height=480, fps=24, duration_s=1.0, seed=1),
    audios=[
        _audio(channels=AudioChannelLayout.FOUR_ZERO, role=AudioTrackRole.MAIN),
        _audio(channels=AudioChannelLayout.LCR, role=AudioTrackRole.COMMENTARY),
        _audio(channels=AudioChannelLayout.STEREO, role=AudioTrackRole.ALTERNATE),
    ],
    audio_inputs=[
        recipe_sine(channels="4.0", duration_s=1.0, seed=1),
        recipe_sine(channels="lcr", duration_s=1.0, seed=2),
        recipe_sine(channels="stereo", duration_s=1.0, seed=3),
    ],
    output_path=tmp_path / "asset.mkv",
)
```

Assert:

```python
def _arg_value(argv: list[str], flag: str) -> str:
    return argv[argv.index(flag) + 1]


assert _arg_value(argv, "-channel_layout:a:1") == "3.0"
metadata_pairs = [
    (argv[index], argv[index + 1])
    for index, arg in enumerate(argv)
    if arg.startswith("-metadata:s:a:")
]
assert ("-metadata:s:a:1", "role=commentary") in metadata_pairs
assert ("-metadata:s:a:1", "title=Commentary") in metadata_pairs
assert ("-metadata:s:a:1", "handler_name=Commentary") in metadata_pairs
assert _arg_value(argv, "-disposition:a:1") == "comment"
```

Run: `uv run pytest --no-cov tests/materializer/test_ffmpeg_builder.py -q`
Expected: FAIL because metadata and layout args are absent.

- [ ] **Step 2: Implement metadata and layout args**

Add:

```python
_AUDIO_TITLE_BY_ROLE: Final[dict[AudioTrackRole, str]] = {
    AudioTrackRole.MAIN: "Main Audio",
    AudioTrackRole.COMMENTARY: "Commentary",
    AudioTrackRole.ALTERNATE: "Alternate Audio",
}
```

Emit per-track:

```python
args.extend([
    f"-channel_layout:a:{index}",
    AUDIO_FFMPEG_CHANNEL_LAYOUT_BY_NAME[audio.channels.value],
])
args.extend([f"-metadata:s:a:{index}", f"language={audio.language}"])
args.extend([f"-metadata:s:a:{index}", f"title={title}"])
args.extend([f"-metadata:s:a:{index}", f"handler_name={title}"])
args.extend([f"-metadata:s:a:{index}", f"role={audio.role.value}"])
if audio.role is AudioTrackRole.COMMENTARY:
    args.extend([f"-disposition:a:{index}", "comment"])
```

Place metadata after `_BITEXACT_OUTPUT_FLAGS` so `-map_metadata -1` runs before
new stream metadata is set.

- [ ] **Step 3: Update audio-only command tests**

Change audio-only tests from `-ac` assertions to `-channel_layout:a:0` assertions:

```python
assert argv[argv.index("-channel_layout:a:0") + 1] == "stereo"
```

For `lcr`, assert `3.0`.

Run:

```bash
uv run pytest --no-cov tests/materializer/test_ffmpeg_builder.py tests/materializer/test_audio_only.py -q
```

Expected: PASS.

Commit:

```bash
git add src/chaos_librarian/materializer/tooling/ffmpeg.py \
  tests/materializer/test_ffmpeg_builder.py tests/materializer/test_audio_only.py
git commit -m "Write audio role stream metadata"
```

### Task 5: Real Materialization Fixture

**Files:**
- Create: `tests/fixtures/scenarios/audio-layout-roles.yaml`
- Modify: `tests/integration/test_materialize_sprint10_real.py`
- Modify: `tests/materializer/test_run.py`
- Modify: `tests/materializer/test_replay.py`

- [ ] **Step 1: Write fixture and failing integration test**

Create one scenario with:

- MKV movie asset `asset_movie_audio_roles` with three AAC audio tracks:
  `4.0/main/eng`, `lcr/commentary/eng`, `stereo/alternate/spa`.
- FLAC track asset `asset_track_six_one` with one `6.1/main/zxx` audio track.

Add integration assertions:

```python
movie_audio = [s for s in movie_version["probed"]["streams"] if s["kind"] == "audio"]
assert [s["language"] for s in movie_audio] == ["eng", "eng", "spa"]
assert [s["channel_layout"] for s in movie_audio] == ["4.0", "3.0", "stereo"]
assert [s["title"] for s in movie_audio] == ["Main Audio", "Commentary", "Alternate Audio"]
assert [s["role"] for s in movie_audio] == ["main", "commentary", "alternate"]
track_audio = [s for s in track_version["probed"]["streams"] if s["kind"] == "audio"]
assert track_audio[0]["channels"] == 7
assert track_audio[0]["channel_layout"] == "6.1"
```

Assert content-source evidence:

```python
by_asset = defaultdict(list)
for source in report["content_sources"]:
    if source["track_kind"] == "audio":
        by_asset[source["asset_id"]].append(source["track_index"])
assert by_asset["asset_movie_audio_roles"] == [0, 1, 2]
assert by_asset["asset_track_six_one"] == [0]
```

Run: `uv run pytest --no-cov tests/integration/test_materialize_sprint10_real.py -q`
Expected: FAIL until implementation is complete.

- [ ] **Step 2: Add run/replay content-source checks**

Add mocked materializer tests proving multi-audio content-source records are
preserved through materialize/run/replay reports.

Run:

```bash
uv run pytest --no-cov tests/materializer/test_run.py tests/materializer/test_replay.py -q
```

Expected: PASS after implementation.

Commit:

```bash
git add tests/fixtures/scenarios/audio-layout-roles.yaml \
  tests/integration/test_materialize_sprint10_real.py \
  tests/materializer/test_run.py tests/materializer/test_replay.py
git commit -m "Cover audio layout role materialization"
```

### Task 6: Schema Regeneration And Version Migration

**Files:**
- Modify: `schemas/*.schema.json`
- Modify: `tests/fixtures/scenarios/**/*.yaml`
- Modify: test literals with `schema_version: 18`
- Modify: `tests/support/adapter.py`
- Modify: generated docs references only where tests require current versions

- [ ] **Step 1: Migrate scenario version literals**

Run a mechanical replacement for current fixtures/tests:

```bash
perl -0pi -e 's/schema_version: 18/schema_version: 19/g' \
  $(rg -l 'schema_version: 18' tests src)
```

Then inspect:

```bash
rg -n 'schema_version: 18|schema_version == 18|Literal\[18\]|SCENARIO_SCHEMA_VERSION == 18' tests src
```

Expected: no output.

- [ ] **Step 2: Regenerate schemas**

Run:

```bash
uv run python -m chaos_librarian.schema_export --write
uv run python -m chaos_librarian.schema_export --check
```

Expected: check reports all 21 schemas up-to-date.

- [ ] **Step 3: Verify schema task**

Run:

```bash
uv run pytest --no-cov tests/contract/test_sample_scenarios.py \
  tests/validation/test_invalid_corpus.py \
  tests/docs/test_documentation.py -q
```

Expected: PASS.

Commit:

```bash
git add schemas tests src docs
git commit -m "Regenerate schemas for audio roles"
```

### Task 7: Review And Final Verification

**Files:**
- Review: full branch diff

- [ ] **Step 1: Run adversarial code review**

Review:

```bash
git diff origin/main...HEAD
```

Address up to three rounds of material findings. Do not count weak style
comments as findings.

- [ ] **Step 2: Run simplification review**

Review the branch diff for duplication or avoidable complexity. Implement the
highest-leverage simplification if it preserves behavior.

- [ ] **Step 3: Final verification**

Run:

```bash
uv run python -m chaos_librarian.schema_export --check
uv run ruff check .
uv run ruff format --check .
uv run ty check src tests
uv run pytest -q
git diff --check
```

Expected: every command exits 0 with no warnings.

- [ ] **Step 4: Push and open PR**

Run:

```bash
git status --short
git push -u origin feat/issue-135-audio-layouts-roles
gh pr create --fill --base main --head feat/issue-135-audio-layouts-roles
```

Monitor checks, merge after green, and close #135 with the implementation and
verification summary.
