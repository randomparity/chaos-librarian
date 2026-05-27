# Issue 134 Audio Recipes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic audio noise, sample-rate, and probe-verifiable sample-format controls for materialize-supported audio tracks.

**Architecture:** Extend `AudioTrack` with explicit recipe parameters, thread them through content-source requests/evidence, and keep validation responsible for the supported codec/container matrix. FFmpeg recipes generate the requested audio source and sample rate; FFmpeg output options enforce per-stream sample rates and sample formats only for the cells where ffprobe reports them reliably.

**Tech Stack:** Pydantic v2 contracts, JSON Schema export, FFmpeg/FFprobe lavfi recipes, Typer capabilities output, pytest, ruff, ty.

---

## Task 1: Contract, Evidence, And Capability Surface

**Files:**
- Modify: `src/chaos_librarian/contract/__init__.py`
- Modify: `src/chaos_librarian/contract/scenario.py`
- Modify: `src/chaos_librarian/contract/content_sources.py`
- Modify: `src/chaos_librarian/contract/capabilities.py`
- Modify: `src/chaos_librarian/materializer/capability_gates.py`
- Modify: `src/chaos_librarian/materializer/content_sources.py`
- Modify: `src/chaos_librarian/materializer/run.py`
- Modify: `src/chaos_librarian/materializer/wall_clock.py`
- Modify: `src/chaos_librarian/materializer/replay.py`
- Modify: `src/chaos_librarian/materializer/tooling/capabilities.py`
- Modify: `src/chaos_librarian/cli/commands/capabilities.py`
- Test: `tests/contract/test_scenario.py`
- Test: `tests/contract/test_content_sources.py`
- Test: `tests/contract/test_capabilities.py`
- Test: `tests/contract/test_contract_constants.py`
- Test: `tests/materializer/test_content_sources.py`
- Test: `tests/materializer/test_capabilities.py`
- Test: `tests/materializer/test_run.py`
- Test: `tests/materializer/test_wall_clock.py`
- Test: `tests/materializer/test_replay.py`
- Test: `tests/cli/test_capabilities.py`

- [ ] **Step 1: Write failing contract tests**

Add tests that expect:

```python
assert scenario_contract.SCENARIO_SCHEMA_VERSION == 18
assert scenario_contract.MATERIALIZATION_SCHEMA_VERSION == 12
assert scenario_contract.REPLAY_BUNDLE_SCHEMA_VERSION == 10
assert scenario_contract.CAPABILITIES_SCHEMA_VERSION == 6
assert AudioSource.NOISE.value == "noise"
assert AudioNoiseColor.WHITE.value == "white"
assert AudioSampleFormat.S24.value == "s24"
```

Add `AudioTrack` round-trip tests:

```python
track = AudioTrack.model_validate(
    {
        "source": "noise",
        "noise_color": "pink",
        "codec": "flac",
        "channels": "stereo",
        "language": "eng",
        "sample_rate": 96000,
        "sample_format": "s24",
    }
)
assert track.source is AudioSource.NOISE
assert track.noise_color is AudioNoiseColor.PINK
assert track.sample_rate == 96000
assert track.sample_format is AudioSampleFormat.S24
```

Add negative tests for `source: noise` without `noise_color` and `noise_color` on
`source: sine`.

Run:

```bash
uv run pytest tests/contract/test_scenario.py \
  tests/contract/test_contract_constants.py -q --no-cov
```

Expected: FAIL because the schema versions, enums, fields, and validators do not exist.

- [ ] **Step 2: Implement contract fields**

Implement:

```python
SCENARIO_SCHEMA_VERSION: Final = 18
MATERIALIZATION_SCHEMA_VERSION: Final = 12
REPLAY_BUNDLE_SCHEMA_VERSION: Final = 10
CAPABILITIES_SCHEMA_VERSION: Final = 6

class AudioSource(enum.StrEnum):
    SINE = "sine"
    SILENCE = "silence"
    CHANNEL_TONES = "channel_tones"
    NOISE = "noise"

class AudioNoiseColor(enum.StrEnum):
    WHITE = "white"
    PINK = "pink"
    BROWN = "brown"

class AudioSampleFormat(enum.StrEnum):
    S16 = "s16"
    S24 = "s24"
    FLT = "flt"

class AudioTrack(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source: AudioSource = AudioSource.SINE
    codec: str
    channels: AudioChannelLayout
    language: str
    noise_color: AudioNoiseColor | None = None
    sample_rate: Literal[8000, 22050, 44100, 48000, 88200, 96000] = 48000
    sample_format: AudioSampleFormat | None = None

    @model_validator(mode="after")
    def _validate_noise_color(self) -> AudioTrack:
        if self.source is AudioSource.NOISE and self.noise_color is None:
            raise ValueError("audio noise source requires noise_color")
        if self.source is not AudioSource.NOISE and self.noise_color is not None:
            raise ValueError("noise_color is only valid with source='noise'")
        return self
```

Run the tests from Step 1. Expected: PASS.

- [ ] **Step 3: Write failing evidence and capability tests**

Add `ContentSourceEvidence` tests for:

```python
evidence = ContentSourceEvidence(
    asset_id="asset_main",
    track_kind=ContentTrackKind.AUDIO,
    track_index=0,
    source="noise",
    provider="builtin-lavfi",
    recipe_digest="sha256:" + "0" * 64,
    noise_color=AudioNoiseColor.BROWN,
    sample_rate=88200,
    sample_format=AudioSampleFormat.FLT,
    cache_disposition=CacheDisposition.NOT_CACHEABLE,
)
assert evidence.noise_color is AudioNoiseColor.BROWN
assert evidence.sample_rate == 88200
assert evidence.sample_format is AudioSampleFormat.FLT
```

Add content-source tests asserting `AudioSourceRequest` carries the three new parameters
and the digest changes when each parameter changes. Add capability tests asserting:

```python
assert caps.ready_for.materialize_audio_recipes is True
assert "audio:noise" in provider.sources
assert "audio:noise:pink" in provider.sources
assert "audio:sample_rate:96000" in provider.sources
assert "audio:sample_format:flt" in provider.sources
```

Also test the unavailable path by monkeypatching FFmpeg filter detection to make
`anoisesrc` unavailable and assert those markers are absent.

Run:

```bash
uv run pytest tests/contract/test_content_sources.py \
  tests/contract/test_capabilities.py \
  tests/materializer/test_content_sources.py \
  tests/materializer/test_capabilities.py \
  tests/cli/test_capabilities.py -q --no-cov
```

Expected: FAIL because evidence, request payloads, and capabilities are not wired.

- [ ] **Step 4: Implement evidence and capability reporting**

Add the three optional fields to `ContentSourceEvidence`. Add them to
`AudioSourceRequest`, `_builtin_evidence()`, and `_request_payload()`.

In `content_sources.py`, add:

```python
AUDIO_NOISE_CAPABILITY_SOURCES = tuple(
    f"audio:noise:{color.value}" for color in AudioNoiseColor
)
AUDIO_SAMPLE_RATE_CAPABILITY_SOURCES = tuple(
    f"audio:sample_rate:{rate}" for rate in SUPPORTED_AUDIO_SAMPLE_RATES
)
AUDIO_SAMPLE_FORMAT_CAPABILITY_SOURCES = tuple(
    f"audio:sample_format:{sample_format.value}" for sample_format in AudioSampleFormat
)
```

Thread `audio_recipes_available` through `collect_content_source_capabilities()` and
include `audio:noise`, the noise color markers, sample-rate markers, and sample-format
markers only when true. Detect the feature with `_ffmpeg_filter_available(ffmpeg,
"anoisesrc")` and set `ReadyFor.materialize_audio_recipes`.

Run the tests from Step 3. Expected: PASS.

- [ ] **Step 5: Write failing capability-gate tests**

Add materialize, wall-clock, and replay tests that patch capabilities with
`materialize_audio_recipes=False`, use a valid scenario containing `source: noise`, and
assert:

```python
assert exc.value.field == "ready_for.materialize_audio_recipes"
```

The tests should also assert the failure happens before run directory allocation when
that entry point normally allocates a run directory.

Run:

```bash
uv run pytest \
  tests/materializer/test_run.py::test_orchestrator_refuses_audio_noise_when_capability_missing \
  tests/materializer/test_wall_clock.py::test_wall_clock_refuses_audio_noise_when_capability_missing \
  tests/materializer/test_replay.py::test_run_replay_refuses_audio_noise_when_capability_missing \
  -q --no-cov
```

Expected: FAIL because no audio recipe capability gate exists.

- [ ] **Step 6: Implement the audio recipe capability gate**

Add `assert_capable_for_audio_recipes()` to `capability_gates.py`. It should scan every
asset audio stream and return unless at least one stream has `source is AudioSource.NOISE`.
When noise is requested and `caps.ready_for.materialize_audio_recipes` is false, raise:

```python
CapabilityGateError(
    "audio noise recipes require ready_for.materialize_audio_recipes",
    field="ready_for.materialize_audio_recipes",
    payload={"asset_id": asset.id},
)
```

Call the gate after the static materialize capability gate in materialize, wall-clock
run, and run replay.

Run the tests from Step 5. Expected: PASS.

## Task 2: Validation And FFmpeg Command Matrix

**Files:**
- Modify: `src/chaos_librarian/media_matrix.py`
- Modify: `src/chaos_librarian/validation/rules/materialize_media_matrix.py`
- Modify: `src/chaos_librarian/materializer/preflight.py`
- Modify: `src/chaos_librarian/materializer/tooling/ffmpeg.py`
- Test: `tests/validation/rules/test_materialize_media_matrix.py`
- Test: `tests/materializer/test_preflight.py`
- Test: `tests/materializer/test_ffmpeg_builder.py`

- [ ] **Step 1: Write failing validation tests**

Add helpers that write scenarios for:

```yaml
audio:
  - source: noise
    noise_color: white
    codec: flac
    channels: stereo
    language: eng
    sample_rate: 96000
    sample_format: s24
```

Add valid cases for AAC at 88200 Hz, FLAC s16/s24, MP3 at 48000 Hz, and WAV
`pcm_f32le` with `sample_format: flt`. Add invalid cases for MP3 at 96000 Hz,
AAC with `sample_format: s16`, FLAC with `sample_format: flt`, and WAV
`pcm_s16le` with `sample_format: s24`.

Run:

```bash
uv run pytest tests/validation/rules/test_materialize_media_matrix.py -q --no-cov
```

Expected: FAIL because the validation rule does not know the new matrix.

- [ ] **Step 2: Implement the validation matrix**

In `media_matrix.py`, add:

```python
SUPPORTED_AUDIO_ONLY_CONTAINERS = frozenset({"flac", "mp3", "m4a", "wav"})
SUPPORTED_AUDIO_SOURCES = frozenset({"sine", "silence", "channel_tones", "noise"})
SUPPORTED_AUDIO_NOISE_COLORS = frozenset({"white", "pink", "brown"})
SUPPORTED_AUDIO_SAMPLE_RATES = frozenset({8000, 22050, 44100, 48000, 88200, 96000})
MP3_SAMPLE_RATES = frozenset({8000, 22050, 44100, 48000})
SUPPORTED_AUDIO_ONLY_CODECS_BY_CONTAINER = {
    "flac": frozenset({"flac"}),
    "mp3": frozenset({"mp3"}),
    "m4a": frozenset({"aac"}),
    "wav": frozenset({"pcm_s16le", "pcm_s24le", "pcm_f32le"}),
}
AUDIO_SAMPLE_FORMATS_BY_CODEC = {
    "flac": frozenset({"s16", "s24"}),
    "pcm_s16le": frozenset({"s16"}),
    "pcm_s24le": frozenset({"s24"}),
    "pcm_f32le": frozenset({"flt"}),
}
AUDIO_ENCODER_BY_CODEC = {
    "aac": "aac",
    "flac": "flac",
    "mp3": "libmp3lame",
    "pcm_s16le": "pcm_s16le",
    "pcm_s24le": "pcm_s24le",
    "pcm_f32le": "pcm_f32le",
}
```

Keep `SUPPORTED_AUDIO_CODECS` for video-backed AAC only. Add `_check_audio()` in the
validation rule and call it for every movie/episode audio stream and the single track
audio stream. Report errors at `audio[<index>].sample_rate` or
`audio[<index>].sample_format`.

Run the validation tests. Expected: PASS.

- [ ] **Step 3: Write failing preflight and command-builder tests**

Add preflight tests that:

```python
preflight_asset(
    parent_kind=ParentKind.TRACK,
    video=None,
    audios=[
        AudioTrack(
            source=AudioSource.NOISE,
            noise_color=AudioNoiseColor.WHITE,
            codec="pcm_f32le",
            channels=AudioChannelLayout.STEREO,
            language="eng",
            sample_rate=96000,
            sample_format=AudioSampleFormat.FLT,
        )
    ],
    subtitles=(),
    container="wav",
)
```

Add `build_command()` tests asserting per-stream output args:

```python
assert ["-c:a:0", "pcm_f32le"] appears in order
assert ["-ar:a:0", "96000"] appears in order
assert ["-sample_fmt:a:0", "flt"] appears in order
```

Run:

```bash
uv run pytest tests/materializer/test_preflight.py \
  tests/materializer/test_ffmpeg_builder.py -q --no-cov
```

Expected: FAIL because preflight requests and FFmpeg output args are not wired.

- [ ] **Step 4: Implement preflight and FFmpeg output args**

Thread `sample_rate`, `sample_format`, and `noise_color` into
`AudioSourceRequest` in preflight. Add `.wav` to `_CONTAINER_FROM_EXTENSION` in
`ffmpeg.py`. Replace global audio output args with a helper:

```python
def _audio_output_args(audios: Sequence[AudioTrack]) -> list[str]:
    args: list[str] = []
    for index, audio in enumerate(audios):
        args.extend([f"-c:a:{index}", AUDIO_ENCODER_BY_CODEC[audio.codec]])
        args.extend([f"-ar:a:{index}", str(audio.sample_rate)])
        if audio.sample_format is not None:
            args.extend([f"-sample_fmt:a:{index}", _ffmpeg_sample_format(audio)])
    return args
```

Map `s24` to FFmpeg `s32`; keep `s16` and `flt` unchanged. Use this helper in both
video-backed and audio-only command builders. Keep `-ac` for audio-only channel count.

Run the tests from Step 3. Expected: PASS.

## Task 3: Recipes, Materialization, Schemas, And Integration

**Files:**
- Modify: `src/chaos_librarian/materializer/tooling/recipes.py`
- Modify: `src/chaos_librarian/materializer/synthesis.py`
- Modify: `tests/materializer/test_recipes.py`
- Modify: `tests/materializer/test_synthesis.py`
- Modify: `tests/integration/test_materialize_real.py`
- Add: `tests/fixtures/scenarios/audio-noise-sample-format.yaml`
- Modify: `docs/contract/schema-reference.md`
- Regenerate: `schemas/scenario.schema.json`
- Regenerate: `schemas/capabilities.schema.json`
- Regenerate: `schemas/materialization.schema.json`
- Regenerate: `schemas/replay-bundle.schema.json`
- Mechanically update fixture/test `schema_version: 17` references to `18`

- [ ] **Step 1: Write failing recipe and synthesis tests**

Add recipe tests:

```python
fi = recipe_noise(
    channels="stereo",
    duration_s=2.0,
    seed=123,
    noise_color=AudioNoiseColor.PINK,
    sample_rate=88200,
    sample_format=AudioSampleFormat.S24,
)
assert "anoisesrc=color=pink:duration=2.0:sample_rate=88200:seed=123" in fi.lavfi
assert "aformat=sample_fmts=s32" in fi.lavfi
```

Add synthesis tests asserting materialized content-source evidence includes
`noise_color`, `sample_rate`, and `sample_format`.

Run:

```bash
uv run pytest tests/materializer/test_recipes.py \
  tests/materializer/test_synthesis.py -q --no-cov
```

Expected: FAIL because the recipe and synthesis request fields are not implemented.

- [ ] **Step 2: Implement recipes and synthesis request threading**

Update all audio recipe call signatures to accept:

```python
noise_color: AudioNoiseColor | None
sample_rate: int
sample_format: AudioSampleFormat | None
```

Use `sample_rate` in every lavfi source. Implement `recipe_noise()` with `anoisesrc`.
Append `aformat=sample_fmts=<fmt>` when `sample_format` is set. Thread the new fields
from `_resolve_media_inputs()` into each `AudioSourceRequest`.

Run the tests from Step 1. Expected: PASS.

- [ ] **Step 3: Add real fixture and integration tests**

Add `tests/fixtures/scenarios/audio-noise-sample-format.yaml` containing an audio-only
track asset with:

```yaml
container: wav
audio:
  - source: noise
    noise_color: brown
    codec: pcm_f32le
    channels: stereo
    language: eng
    sample_rate: 96000
    sample_format: flt
```

Add a real FFmpeg integration test that materializes the fixture, runs raw ffprobe, and
asserts:

```python
assert stream["codec_name"] == "pcm_f32le"
assert stream["sample_rate"] == "96000"
assert stream["sample_fmt"] == "flt"
assert stream["bits_per_sample"] == 32
```

Run:

```bash
uv run pytest tests/integration/test_materialize_real.py::test_materialize_audio_noise_sample_format_reports_probe_metadata -q --no-cov
```

Expected: FAIL before implementation is complete; PASS after recipe and command wiring are in place.

- [ ] **Step 4: Regenerate schemas and update current-version fixtures**

Run:

```bash
uv run python -m chaos_librarian.schema_export --write
```

Mechanically update current scenario fixtures and tests from schema version 17 to 18.
Update `docs/contract/schema-reference.md` so it lists Scenario v18, Capabilities v6,
Materialization v12, and Replay Bundle v10 with a short v18 note.

Run:

```bash
uv run python -m chaos_librarian.schema_export --check
uv run pytest tests/contract/test_sample_scenarios.py \
  tests/contract/test_contract_constants.py -q --no-cov
```

Expected: PASS.

## Task 4: Reviews, Final Verification, PR, And Closure

**Files:**
- Review all changed files from Tasks 1-3.

- [ ] **Step 1: Run adversarial implementation review**

Review `git diff origin/main...HEAD` with focus on unsupported combinations silently
materializing, schema drift, and evidence gaps. Address material findings. Run no more
than three adversarial implementation reviews.

- [ ] **Step 2: Run simplification review**

Review the completed diff for unnecessary abstractions and duplication. Address the most
relevant low-risk recommendations only.

- [ ] **Step 3: Run final verification**

Run:

```bash
uv run python -m chaos_librarian.schema_export --check
uv run ruff check .
uv run ruff format --check .
uv run ty check src tests
uv run pytest -q
git diff --check
```

Expected: all commands exit 0.

- [ ] **Step 4: Commit, push, PR, monitor, merge, close**

Commit with:

```bash
git add --all
git commit -m "Add audio noise and sample-format recipes"
git push -u origin feat/issue-134-audio-recipes
```

Open a PR whose body includes the final verification commands and `Closes #134`.
Monitor GitHub checks. If checks pass, merge through GitHub, confirm issue #134 is
closed, and delete the remote branch if GitHub did not.
