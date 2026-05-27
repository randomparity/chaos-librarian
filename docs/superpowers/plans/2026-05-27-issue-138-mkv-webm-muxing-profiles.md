# MKV/WebM Muxing Profiles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add scenario-selectable MKV/WebM cue and cluster muxing profiles backed by mkvmerge, with minimal WebM VP9 support.

**Architecture:** Contracts add `Asset.matroska_muxing_profile` and profile evidence. FFmpeg continues to synthesize media streams; when a profile is requested, FFmpeg writes a temporary Matroska/WebM input and mkvmerge remuxes the final file with cue/cluster options. Validation and capability gates reject unsupported profile, WebM, and toolchain combinations before run-dir allocation.

**Tech Stack:** Python 3.13, Pydantic v2, Typer CLI contracts, FFmpeg/FFprobe, mkvmerge/mkvinfo from mkvtoolnix, pytest, ruff, ty.

---

## File Map

- Modify `src/chaos_librarian/contract/scenario.py`: add `MatroskaMuxingProfile` enum and `Asset.matroska_muxing_profile`; bump scenario literal to `22`.
- Modify `src/chaos_librarian/contract/__init__.py`: bump `SCENARIO_SCHEMA_VERSION`, `MATERIALIZATION_SCHEMA_VERSION`, `REPLAY_BUNDLE_SCHEMA_VERSION`, and `CAPABILITIES_SCHEMA_VERSION`.
- Modify `src/chaos_librarian/contract/content_sources.py`: add `ContentTrackKind.MUXING`, enum-typed `matroska_muxing_profile`, and `container`.
- Modify `src/chaos_librarian/contract/materialization.py` and `src/chaos_librarian/contract/replay_bundle.py`: bump literals to `15` and `12`.
- Modify `src/chaos_librarian/contract/capabilities.py`: add two readiness fields and bump literal to `7`.
- Modify `src/chaos_librarian/media_matrix.py`: add `webm`, `vp9`, container-specific video codec rules, and `libvpx-vp9`.
- Modify `src/chaos_librarian/materializer/tooling/ffmpeg.py`: validate codec by container and emit VP9 args without unused x264/x265 preset flags.
- Create `src/chaos_librarian/materializer/tooling/mkvmerge.py`: build/run mkvmerge remux commands for the three profiles.
- Modify `src/chaos_librarian/materializer/tooling/capabilities.py`, `src/chaos_librarian/materializer/capability_gates.py`, and `src/chaos_librarian/materializer/run.py`: detect/gate mkvmerge and VP9 support.
- Modify `src/chaos_librarian/validation/rules/materialize_media_matrix.py`: raw validation for muxing profile and minimal WebM cell.
- Modify `src/chaos_librarian/materializer/preflight.py` and `src/chaos_librarian/materializer/synthesis.py`: thread profile requests into preflight and mkvmerge finalization.
- Modify `docs/contract/schema-reference.md` and generated `schemas/*.schema.json`.
- Add focused tests under `tests/contract/`, `tests/validation/rules/`, `tests/materializer/`, and invalid fixtures under `tests/fixtures/scenarios/invalid/`.

---

### Task 1: Contract Shapes and Schema Versions

**Files:**
- Modify: `src/chaos_librarian/contract/scenario.py`
- Modify: `src/chaos_librarian/contract/__init__.py`
- Modify: `src/chaos_librarian/contract/content_sources.py`
- Modify: `src/chaos_librarian/contract/materialization.py`
- Modify: `src/chaos_librarian/contract/replay_bundle.py`
- Modify: `src/chaos_librarian/contract/capabilities.py`
- Test: `tests/contract/test_scenario.py`
- Test: `tests/contract/test_contract_constants.py`
- Test: `tests/contract/test_materialization.py`
- Test: `tests/contract/test_replay_bundle.py`
- Test: `tests/contract/test_capabilities.py`

- [ ] **Step 1: Write failing scenario contract tests**

Add to `tests/contract/test_scenario.py`:

```python
def test_asset_accepts_matroska_muxing_profile_values() -> None:
    payload = _minimal_scenario().model_dump(mode="json")
    asset = payload["movies"][0]["variants"][0]["bundle"]["assets"][0]
    for profile in ("no_cues", "dense_cues", "short_clusters"):
        asset["matroska_muxing_profile"] = profile
        scenario = Scenario.model_validate(payload)
        loaded = scenario.movies[0].variants[0].bundle.assets[0]
        assert loaded.matroska_muxing_profile is not None
        assert loaded.matroska_muxing_profile.value == profile
```

Add to `tests/contract/test_contract_constants.py`:

```python
def test_issue_138_schema_versions() -> None:
    assert SCENARIO_SCHEMA_VERSION == 22
    assert MATERIALIZATION_SCHEMA_VERSION == 15
    assert REPLAY_BUNDLE_SCHEMA_VERSION == 12
    assert CAPABILITIES_SCHEMA_VERSION == 7
```

- [ ] **Step 2: Write failing evidence and capability contract tests**

Add to `tests/contract/test_materialization.py` near existing content-source tests:

```python
def test_materialization_content_source_carries_muxing_profile() -> None:
    evidence = ContentSourceEvidence(
        asset_id="asset_main",
        track_kind=ContentTrackKind.MUXING,
        source="short_clusters",
        provider="builtin-mkvmerge",
        recipe_digest="sha256:" + "1" * 64,
        matroska_muxing_profile="short_clusters",
        container="mkv",
        cache_disposition=CacheDisposition.NOT_CACHEABLE,
    )
    loaded = ContentSourceEvidence.model_validate(evidence.model_dump(mode="json"))
    assert loaded.track_kind is ContentTrackKind.MUXING
    assert loaded.matroska_muxing_profile is MatroskaMuxingProfile.SHORT_CLUSTERS
    assert loaded.container == "mkv"
```

Add an equivalent assertion in `tests/contract/test_replay_bundle.py` by extending the existing materialize bundle content-source evidence test with:

```python
payload["content_sources"].append(
    {
        "asset_id": "asset_main",
        "track_kind": "muxing",
        "source": "no_cues",
        "provider": "builtin-mkvmerge",
        "recipe_digest": "sha256:" + "2" * 64,
        "matroska_muxing_profile": "no_cues",
        "container": "webm",
        "cache_disposition": "not_cacheable",
    }
)
```

Add to `tests/contract/test_capabilities.py`:

```python
def test_capabilities_ready_for_muxing_profiles_round_trips() -> None:
    caps = Capabilities(
        schema_version=CAPABILITIES_SCHEMA_VERSION,
        ffmpeg=ToolStatus(found=True, version="7.1", path="/x/ffmpeg", meets_minimum=True),
        ffprobe=ToolStatus(found=True, version="7.1", path="/x/ffprobe", meets_minimum=True),
        mkvtoolnix=ToolStatus(found=True, version="98", path="/x/mkvmerge", meets_minimum=True),
        platform="test",
        content_sources=ContentSourceCapabilities(),
        ready_for=ReadyFor(
            materialize_static=True,
            materialize_filesystem_mutations=True,
            materialize_media_mutations=True,
            materialize_hevc_video=True,
            materialize_hdr_video=True,
            materialize_resolution_switch_video=True,
            materialize_audio_recipes=True,
            materialize_matroska_muxing_profiles=True,
            materialize_webm_video=True,
        ),
    )
    loaded = Capabilities.model_validate_json(caps.model_dump_json())
    assert loaded.ready_for.materialize_matroska_muxing_profiles
    assert loaded.ready_for.materialize_webm_video
```

- [ ] **Step 3: Run tests to verify red**

Run:

```bash
uv run pytest --no-cov \
  tests/contract/test_scenario.py::test_asset_accepts_matroska_muxing_profile_values \
  tests/contract/test_contract_constants.py::test_issue_138_schema_versions \
  tests/contract/test_materialization.py::test_materialization_content_source_carries_muxing_profile \
  tests/contract/test_capabilities.py::test_capabilities_ready_for_muxing_profiles_round_trips \
  -q
```

Expected: failures for missing enum/fields and stale schema-version constants.

- [ ] **Step 4: Implement contract changes**

In `src/chaos_librarian/contract/scenario.py`:

```python
class MatroskaMuxingProfile(enum.StrEnum):
    """Matroska/WebM muxing profiles for cue and cluster parser surfaces."""

    NO_CUES = "no_cues"
    DENSE_CUES = "dense_cues"
    SHORT_CLUSTERS = "short_clusters"
```

Add to `Asset`:

```python
matroska_muxing_profile: MatroskaMuxingProfile | None = None
```

Change `Scenario.schema_version` literal to `Literal[22]`.

In `src/chaos_librarian/contract/__init__.py`:

```python
SCENARIO_SCHEMA_VERSION: Final = 22
REPLAY_BUNDLE_SCHEMA_VERSION: Final = 12
MATERIALIZATION_SCHEMA_VERSION: Final = 15
CAPABILITIES_SCHEMA_VERSION: Final = 7
```

In `content_sources.py`:

```python
class ContentTrackKind(enum.StrEnum):
    VIDEO = "video"
    AUDIO = "audio"
    SUBTITLE = "subtitle"
    CHAPTERS = "chapters"
    COVER_ART = "cover_art"
    MUXING = "muxing"
```

Add optional fields to `ContentSourceEvidence`:

```python
matroska_muxing_profile: MatroskaMuxingProfile | None = None
container: str | None = None
```

In `capabilities.py`, change `Capabilities.schema_version` to `Literal[7]` and add to `ReadyFor`:

```python
materialize_matroska_muxing_profiles: bool
materialize_webm_video: bool
```

In `materialization.py`, change `schema_version: Literal[14]` to `Literal[15]`.
In `replay_bundle.py`, change materialize/run replay literals from `Literal[11]` to `Literal[12]`.

- [ ] **Step 5: Run green tests and commit**

Run:

```bash
uv run pytest --no-cov \
  tests/contract/test_scenario.py::test_asset_accepts_matroska_muxing_profile_values \
  tests/contract/test_contract_constants.py::test_issue_138_schema_versions \
  tests/contract/test_materialization.py::test_materialization_content_source_carries_muxing_profile \
  tests/contract/test_capabilities.py::test_capabilities_ready_for_muxing_profiles_round_trips \
  -q
uv run ruff check src/chaos_librarian/contract tests/contract
```

Expected: all selected tests pass and ruff reports no issues.

Commit:

```bash
git add src/chaos_librarian/contract tests/contract
git commit -m "Add muxing profile contract shapes"
```

---

### Task 2: Validation Matrix

**Files:**
- Modify: `src/chaos_librarian/validation/rules/materialize_media_matrix.py`
- Modify: `tests/validation/rules/test_materialize_media_matrix.py`
- Add: `tests/fixtures/scenarios/invalid/matroska-profile-mp4.yaml`
- Add: `tests/fixtures/scenarios/invalid/matroska-profile-audio-track.yaml`
- Add: `tests/fixtures/scenarios/invalid/webm-without-profile.yaml`
- Add: `tests/fixtures/scenarios/invalid/webm-audio.yaml`
- Add: `tests/fixtures/scenarios/invalid/webm-h264.yaml`

- [ ] **Step 1: Write failing validation tests**

Add helpers to `tests/validation/rules/test_materialize_media_matrix.py` by extending the existing scenario helper to accept:

```python
container: str = "mkv",
video_codec: str = "h264",
audio_block: str = _AAC_AUDIO,
matroska_muxing_profile: str | None = None,
video_extra: str = "",
```

Then add tests:

```python
@pytest.mark.parametrize("profile", ["no_cues", "dense_cues", "short_clusters"])
def test_matroska_muxing_profiles_validate_for_mkv(profile: str) -> None:
    report = _validate(_scenario(matroska_muxing_profile=profile))
    assert report.ok


@pytest.mark.parametrize("profile", ["no_cues", "dense_cues", "short_clusters"])
def test_matroska_muxing_profiles_validate_for_webm_vp9(profile: str) -> None:
    report = _validate(
        _scenario(
            container="webm",
            video_codec="vp9",
            audio_block="",
            matroska_muxing_profile=profile,
        )
    )
    assert report.ok


def test_matroska_muxing_profile_rejects_mp4() -> None:
    report = _validate(_scenario(container="mp4", matroska_muxing_profile="no_cues"))
    assert _messages(report) == ["matroska_muxing_profile is only supported for mkv and webm video assets"]


def test_webm_requires_matroska_muxing_profile() -> None:
    report = _validate(_scenario(container="webm", video_codec="vp9", audio_block=""))
    assert _messages(report) == ["webm assets are only supported with matroska_muxing_profile"]


def test_webm_rejects_audio_streams() -> None:
    report = _validate(
        _scenario(
            container="webm",
            video_codec="vp9",
            matroska_muxing_profile="short_clusters",
        )
    )
    assert _messages(report) == ["webm materialization does not support audio streams"]


def test_webm_rejects_h264() -> None:
    report = _validate(
        _scenario(
            container="webm",
            video_codec="h264",
            audio_block="",
            matroska_muxing_profile="short_clusters",
        )
    )
    assert _messages(report) == ["webm materialization requires video.codec='vp9'"]
```

Add a resolution-switch rejection assertion beside the existing resolution-switch metadata test:

```python
def test_resolution_switch_rejects_matroska_muxing_profile() -> None:
    report = _validate(_resolution_switch_scenario("matroska_muxing_profile: short_clusters\n"))
    assert _messages(report) == [
        "matroska_muxing_profile cannot be combined with resolution-switch video materialization"
    ]
```

- [ ] **Step 2: Add invalid fixtures**

Each invalid fixture must start with an expected code marker.

`tests/fixtures/scenarios/invalid/matroska-profile-mp4.yaml`:

```yaml
# expected: E_MATERIALIZE_UNSUPPORTED
schema_version: 22
scenario_id: matroska-profile-mp4
seed: 138
duration_scale: short
library:
  roots:
    - {id: primary, path: library}
movies:
  - id: movie_1
    title: Movie
    layout: movie_flat
    variants:
      - id: variant_1
        label: default
        bundle:
          id: bundle_1
          assets:
            - id: asset_1
              role: main
              container: mp4
              duration_seconds: 1
              matroska_muxing_profile: no_cues
              video: {source: color_bars, codec: h264, resolution: sd}
              audio:
                - {source: sine, codec: aac, channels: stereo, language: eng}
series: []
artists: []
timeline: []
```

For the other four fixtures, use these exact YAML bodies.

`tests/fixtures/scenarios/invalid/matroska-profile-audio-track.yaml`:

```yaml
# expected: E_MATERIALIZE_UNSUPPORTED
schema_version: 22
scenario_id: matroska-profile-audio-track
seed: 138
duration_scale: short
library:
  roots:
    - {id: music_root, path: music}
movies: []
series: []
artists:
  - id: artist_1
    name: Artist
    layout: artist_album_flat
    track_naming: track_number_title
    albums:
      - id: album_1
        title: Album
        discs:
          - id: disc_1
            disc_number: 1
            tracks:
              - id: track_1
                track_number: 1
                title: Track
                variants:
                  - id: variant_1
                    label: flac
                    bundle:
                      id: bundle_1
                      assets:
                        - id: asset_1
                          role: main
                          container: flac
                          duration_seconds: 1
                          matroska_muxing_profile: no_cues
                          audio:
                            - {source: sine, codec: flac, channels: stereo, language: eng}
timeline: []
```

`tests/fixtures/scenarios/invalid/webm-without-profile.yaml`:

```yaml
# expected: E_MATERIALIZE_UNSUPPORTED
schema_version: 22
scenario_id: webm-without-profile
seed: 138
duration_scale: short
library:
  roots:
    - {id: primary, path: library}
movies:
  - id: movie_1
    title: Movie
    layout: movie_flat
    variants:
      - id: variant_1
        label: default
        bundle:
          id: bundle_1
          assets:
            - id: asset_1
              role: main
              container: webm
              duration_seconds: 1
              video: {source: color_bars, codec: vp9, resolution: sd}
series: []
artists: []
timeline: []
```

`tests/fixtures/scenarios/invalid/webm-audio.yaml`:

```yaml
# expected: E_MATERIALIZE_UNSUPPORTED
schema_version: 22
scenario_id: webm-audio
seed: 138
duration_scale: short
library:
  roots:
    - {id: primary, path: library}
movies:
  - id: movie_1
    title: Movie
    layout: movie_flat
    variants:
      - id: variant_1
        label: default
        bundle:
          id: bundle_1
          assets:
            - id: asset_1
              role: main
              container: webm
              duration_seconds: 1
              matroska_muxing_profile: short_clusters
              video: {source: color_bars, codec: vp9, resolution: sd}
              audio:
                - {source: sine, codec: aac, channels: stereo, language: eng}
series: []
artists: []
timeline: []
```

`tests/fixtures/scenarios/invalid/webm-h264.yaml`:

```yaml
# expected: E_MATERIALIZE_UNSUPPORTED
schema_version: 22
scenario_id: webm-h264
seed: 138
duration_scale: short
library:
  roots:
    - {id: primary, path: library}
movies:
  - id: movie_1
    title: Movie
    layout: movie_flat
    variants:
      - id: variant_1
        label: default
        bundle:
          id: bundle_1
          assets:
            - id: asset_1
              role: main
              container: webm
              duration_seconds: 1
              matroska_muxing_profile: short_clusters
              video: {source: color_bars, codec: h264, resolution: sd}
series: []
artists: []
timeline: []
```

- [ ] **Step 3: Run tests to verify red**

Run:

```bash
uv run pytest --no-cov \
  tests/validation/rules/test_materialize_media_matrix.py \
  tests/validation/test_invalid_corpus.py \
  -q
```

Expected: new validation cases fail because no rule exists yet.

- [ ] **Step 4: Implement validation**

In `materialize_media_matrix.py`, add constants:

```python
_MATROSKA_PROFILE_CONTAINERS = frozenset({"mkv", "webm"})
_WEBM_REJECTED_VIDEO_FIELDS = (
    "vfr_cadence",
    "field_order",
    "color_space",
    "color_range",
    "hdr_mode",
    "resolution_sequence",
)
```

Call a new helper from `_check_video_asset` before ordinary codec checks:

```python
_check_matroska_muxing_profile(asset=asset, video=video, asset_loc=asset_loc, reporter=reporter)
```

Implement:

```python
def _check_matroska_muxing_profile(
    *,
    asset: Mapping[str, object],
    video: Mapping[str, object],
    asset_loc: _Loc,
    reporter: Reporter,
) -> None:
    profile = asset.get("matroska_muxing_profile")
    container = asset.get("container")
    if isinstance(profile, str) and container not in _MATROSKA_PROFILE_CONTAINERS:
        reporter.error(
            code=E_MATERIALIZE_UNSUPPORTED,
            message="matroska_muxing_profile is only supported for mkv and webm video assets",
            loc=(*asset_loc, "matroska_muxing_profile"),
        )
    if container == "webm":
        _check_webm_asset(asset=asset, video=video, asset_loc=asset_loc, reporter=reporter)
```

Implement `_check_webm_asset` to emit the exact messages from the tests for missing profile, non-`vp9` codec, audio streams, subtitles, and any field in `_WEBM_REJECTED_VIDEO_FIELDS`.

Update `_reject_embedded_metadata_for_asset` pattern with `_reject_matroska_muxing_profile_for_asset` for track assets and resolution-switch assets.

- [ ] **Step 5: Run green validation and commit**

Run:

```bash
uv run pytest --no-cov \
  tests/validation/rules/test_materialize_media_matrix.py \
  tests/validation/test_invalid_corpus.py \
  -q
uv run ruff check src/chaos_librarian/validation/rules/materialize_media_matrix.py tests/validation/rules/test_materialize_media_matrix.py
```

Commit:

```bash
git add src/chaos_librarian/validation/rules/materialize_media_matrix.py tests/validation tests/fixtures/scenarios/invalid
git commit -m "Validate muxing profile matrix"
```

---

### Task 3: Capabilities, Media Matrix, and FFmpeg WebM VP9

**Files:**
- Modify: `src/chaos_librarian/media_matrix.py`
- Modify: `src/chaos_librarian/materializer/tooling/ffmpeg.py`
- Modify: `src/chaos_librarian/materializer/tooling/capabilities.py`
- Modify: `src/chaos_librarian/materializer/capability_gates.py`
- Modify: `src/chaos_librarian/materializer/run.py`
- Modify: `src/chaos_librarian/materializer/preflight.py`
- Test: `tests/materializer/test_ffmpeg_builder.py`
- Test: `tests/materializer/test_capabilities.py`
- Test: `tests/materializer/test_run.py`
- Test: `tests/materializer/test_replay.py`

- [ ] **Step 1: Write failing FFmpeg builder tests**

Add to `tests/materializer/test_ffmpeg_builder.py`:

```python
def test_webm_vp9_video_only_command_uses_libvpx_without_preset(tmp_path: Path) -> None:
    argv = build_command(
        video=_video(codec="vp9"),
        video_input=recipe_color_bars(width=640, height=480, fps=24, duration_s=1.0, seed=1),
        audios=[],
        audio_inputs=[],
        output_path=tmp_path / "asset.webm",
    )
    assert argv[argv.index("-c:v") + 1] == "libvpx-vp9"
    assert "-preset" not in argv
    assert "-deadline" in argv
    assert "-cpu-used" in argv


def test_webm_rejects_audio_inputs(tmp_path: Path) -> None:
    with pytest.raises(UnsupportedMaterializationError) as exc:
        build_command(
            video=_video(codec="vp9"),
            video_input=recipe_color_bars(width=640, height=480, fps=24, duration_s=1.0, seed=1),
            audios=[_audio()],
            audio_inputs=[recipe_sine(channels="stereo", duration_s=1.0, seed=1)],
            output_path=tmp_path / "asset.webm",
        )
    assert exc.value.field == "audio"


def test_mp4_rejects_vp9_codec(tmp_path: Path) -> None:
    with pytest.raises(UnsupportedMaterializationError) as exc:
        build_command(
            video=_video(codec="vp9"),
            video_input=recipe_color_bars(width=640, height=480, fps=24, duration_s=1.0, seed=1),
            audios=[],
            audio_inputs=[],
            output_path=tmp_path / "asset.mp4",
        )
    assert exc.value.field == "video.codec"
```

- [ ] **Step 2: Write failing capability tests**

Add to `tests/materializer/test_capabilities.py`:

```python
def test_detect_capabilities_reports_muxing_and_webm_readiness(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_toolchain(monkeypatch, encoders=" V....D libx264\n V....D libvpx-vp9\n", filters="")
    caps = detect_capabilities()
    assert caps.ready_for.materialize_matroska_muxing_profiles
    assert caps.ready_for.materialize_webm_video


def test_detect_capabilities_webm_not_ready_without_vp9(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_toolchain(monkeypatch, encoders=" V....D libx264\n", filters="")
    caps = detect_capabilities()
    assert caps.ready_for.materialize_matroska_muxing_profiles
    assert not caps.ready_for.materialize_webm_video
```

Use the existing test helper names in the file; if `_patch_toolchain` does not exist, extend the existing subprocess monkeypatch helper instead of adding a parallel helper.

Add capability-gate tests to `tests/materializer/test_run.py` and `tests/materializer/test_replay.py` that monkeypatch `detect_capabilities()` to return `materialize_matroska_muxing_profiles=False` for an MKV profile scenario and `materialize_webm_video=False` for a WebM profile scenario. Assert `CapabilityGateError.field` equals the corresponding `ready_for.*` field.

- [ ] **Step 3: Run tests to verify red**

Run:

```bash
uv run pytest --no-cov \
  tests/materializer/test_ffmpeg_builder.py::test_webm_vp9_video_only_command_uses_libvpx_without_preset \
  tests/materializer/test_ffmpeg_builder.py::test_webm_rejects_audio_inputs \
  tests/materializer/test_ffmpeg_builder.py::test_mp4_rejects_vp9_codec \
  tests/materializer/test_capabilities.py \
  -q
```

Expected: failures for unknown `.webm`, missing `vp9`, and missing readiness fields.

- [ ] **Step 4: Implement media matrix and FFmpeg args**

In `media_matrix.py`, replace flat video codec support with container-specific support:

```python
SUPPORTED_VIDEO_CODECS_BY_CONTAINER: Final[dict[str, frozenset[str]]] = {
    "mkv": frozenset({"h264", "h265", "hevc"}),
    "mp4": frozenset({"h264", "h265", "hevc"}),
    "webm": frozenset({"vp9"}),
}
SUPPORTED_VIDEO_CONTAINERS: Final[frozenset[str]] = frozenset(SUPPORTED_VIDEO_CODECS_BY_CONTAINER)
SUPPORTED_VIDEO_CODECS: Final[frozenset[str]] = frozenset(
    codec for codecs in SUPPORTED_VIDEO_CODECS_BY_CONTAINER.values() for codec in codecs
)
VIDEO_ENCODER_BY_CODEC: Final[dict[str, str]] = {
    "h264": "libx264",
    "h265": "libx265",
    "hevc": "libx265",
    "vp9": "libvpx-vp9",
}
```

In `ffmpeg.py`, add `.webm` to `_CONTAINER_FROM_EXTENSION`, pass `container` into `_validate_video`, and reject WebM audio:

```python
def _validate_video(*, container: str, video: VideoTrack) -> None:
    _require(video.resolution, SUPPORTED_RESOLUTIONS, "video.resolution")
    supported_codecs = SUPPORTED_VIDEO_CODECS_BY_CONTAINER[container]
    _require(video.codec, supported_codecs, "video.codec")
```

Add:

```python
def _video_encoder_args(video: VideoTrack) -> list[str]:
    encoder = VIDEO_ENCODER_BY_CODEC[video.codec]
    args = ["-c:v", encoder]
    if encoder in {"libx264", "libx265"}:
        args.extend(["-preset", "medium"])
    if encoder == "libvpx-vp9":
        args.extend(["-deadline", "good", "-cpu-used", "4", "-b:v", "600k"])
    return args
```

Use `_video_encoder_args(video)` instead of the old hard-coded encoder and
`-preset medium` argument slice.

Add:

```python
if container == "webm" and audios:
    raise UnsupportedMaterializationError(
        "webm materialization does not support audio streams",
        field="audio",
        payload={"count": len(audios)},
    )
```

- [ ] **Step 5: Implement readiness detection and gates**

In `tooling/capabilities.py`, detect VP9:

```python
libvpx_vp9_available = _ffmpeg_encoder_available(ffmpeg, "libvpx-vp9")
```

Set:

```python
materialize_matroska_muxing_profiles=ffmpeg_ok and ffprobe_ok and mkv_ok,
materialize_webm_video=ffmpeg_ok and ffprobe_ok and libvpx_vp9_available,
```

In `capability_gates.py`, add:

```python
def assert_capable_for_matroska_muxing_profiles(scenario: Scenario, caps: Capabilities) -> None:
    for asset in iter_assets(scenario):
        if asset.matroska_muxing_profile is None:
            continue
        if caps.ready_for.materialize_matroska_muxing_profiles:
            return
        raise CapabilityGateError(
            "Matroska/WebM muxing profiles require mkvmerge",
            asset_id=asset.id,
            field="ready_for.materialize_matroska_muxing_profiles",
            payload={"capability": "ready_for.materialize_matroska_muxing_profiles"},
        )


def assert_capable_for_webm_video(scenario: Scenario, caps: Capabilities) -> None:
    for asset in iter_assets(scenario):
        if asset.container != "webm":
            continue
        if caps.ready_for.materialize_webm_video:
            return
        raise CapabilityGateError(
            "WebM materialization requires FFmpeg with libvpx-vp9",
            asset_id=asset.id,
            field="ready_for.materialize_webm_video",
            payload={"capability": "ready_for.materialize_webm_video", "required_encoder": "libvpx-vp9"},
        )
```

Call both from `materializer/run.py` after `assert_capable_for_static_materialize(caps)`.

Update `preflight_asset` signature to accept `matroska_muxing_profile` if needed for WebM/profile rejection, and update callers in `run.py`.

- [ ] **Step 6: Run green tests and commit**

Run:

```bash
uv run pytest --no-cov \
  tests/materializer/test_ffmpeg_builder.py \
  tests/materializer/test_capabilities.py \
  tests/materializer/test_run.py \
  tests/materializer/test_replay.py \
  -q
uv run ruff check src/chaos_librarian/media_matrix.py src/chaos_librarian/materializer tests/materializer
```

Commit:

```bash
git add src/chaos_librarian/media_matrix.py src/chaos_librarian/materializer tests/materializer
git commit -m "Gate WebM and muxing profile capabilities"
```

---

### Task 4: mkvmerge Remux and Replay Evidence

**Files:**
- Create: `src/chaos_librarian/materializer/tooling/mkvmerge.py`
- Modify: `src/chaos_librarian/materializer/content_sources.py`
- Modify: `src/chaos_librarian/materializer/synthesis.py`
- Test: `tests/materializer/test_mkvmerge_builder.py`
- Test: `tests/materializer/test_content_sources.py`
- Test: `tests/materializer/test_synthesis.py`

- [ ] **Step 1: Write failing mkvmerge builder tests**

Create `tests/materializer/test_mkvmerge_builder.py`:

```python
from pathlib import Path

from chaos_librarian.contract.scenario import MatroskaMuxingProfile
from chaos_librarian.materializer.tooling.mkvmerge import build_mkvmerge_command


def test_no_cues_command_emits_deterministic_common_args(tmp_path: Path) -> None:
    argv = build_mkvmerge_command(
        input_path=tmp_path / "in.mkv",
        output_path=tmp_path / "out.mkv",
        container="mkv",
        profile=MatroskaMuxingProfile.NO_CUES,
        deterministic_seed=138,
    )
    assert argv[:2] == ["mkvmerge", "--quiet"]
    assert "--deterministic" in argv
    assert argv[argv.index("--deterministic") + 1] == "138"
    assert "--no-date" in argv
    assert "--disable-track-statistics-tags" in argv
    assert "--no-cues" in argv


def test_dense_cues_targets_primary_video_track_zero(tmp_path: Path) -> None:
    argv = build_mkvmerge_command(
        input_path=tmp_path / "in.mkv",
        output_path=tmp_path / "out.mkv",
        container="mkv",
        profile=MatroskaMuxingProfile.DENSE_CUES,
        deterministic_seed=138,
    )
    assert argv[argv.index("--cues") + 1] == "0:all"


def test_webm_command_uses_webm_output_flag(tmp_path: Path) -> None:
    argv = build_mkvmerge_command(
        input_path=tmp_path / "in.webm",
        output_path=tmp_path / "out.webm",
        container="webm",
        profile=MatroskaMuxingProfile.SHORT_CLUSTERS,
        deterministic_seed=138,
    )
    assert "--webm" in argv
    assert argv[argv.index("--cluster-length") + 1] == "250ms"
```

- [ ] **Step 2: Write failing content-source and synthesis tests**

Add to `tests/materializer/test_content_sources.py`:

```python
def test_resolve_muxing_source_records_profile_and_seed() -> None:
    resolution = resolve_muxing_source(
        MuxingSourceRequest(
            asset_id="asset_1",
            seed=138,
            container="mkv",
            profile=MatroskaMuxingProfile.NO_CUES,
        )
    )
    assert resolution.deterministic_seed >= 0
    assert resolution.evidence.track_kind is ContentTrackKind.MUXING
    assert resolution.evidence.source == "no_cues"
    assert resolution.evidence.provider == "builtin-mkvmerge"
    assert resolution.evidence.matroska_muxing_profile is MatroskaMuxingProfile.NO_CUES
    assert resolution.evidence.container == "mkv"
```

Add to `tests/materializer/test_synthesis.py`:

```python
def test_materialize_one_asset_uses_mkvmerge_final_invocation_for_profile(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    asset = _asset(container="mkv", matroska_muxing_profile=MatroskaMuxingProfile.SHORT_CLUSTERS)
    calls: list[list[str]] = []

    def fake_run_ffmpeg(argv: list[str], *, ffmpeg_version: str, timeout_s: float = 60.0):
        calls.append(argv)
        _touch_output(Path(argv[-1]))
        return ToolInvocation(tool="ffmpeg", version=ffmpeg_version, command=argv, exit_code=0, duration_ns=1), ""

    def fake_run_mkvmerge(argv: list[str], *, mkvmerge_version: str, timeout_s: float = 60.0):
        calls.append(argv)
        _touch_output(Path(argv[argv.index("-o") + 1]))
        return ToolInvocation(tool="mkvmerge", version=mkvmerge_version, command=argv, exit_code=0, duration_ns=1), ""

    monkeypatch.setattr(synthesis_mod, "run_ffmpeg", fake_run_ffmpeg)
    monkeypatch.setattr(synthesis_mod, "run_mkvmerge", fake_run_mkvmerge)
    monkeypatch.setattr(synthesis_mod, "probe_file", lambda path: _probe(path))

    result = materialize_one_asset(asset, 138, tmp_path / "run", _caps(mkvtoolnix=True), 0, rendered_relative_path="r/A.mkv")

    assert result.invocation.tool == "mkvmerge"
    assert result.prelude_invocations[0].tool == "ffmpeg"
    assert any(source.track_kind is ContentTrackKind.MUXING for source in result.content_sources)
```

- [ ] **Step 3: Run tests to verify red**

Run:

```bash
uv run pytest --no-cov \
  tests/materializer/test_mkvmerge_builder.py \
  tests/materializer/test_content_sources.py::test_resolve_muxing_source_records_profile_and_seed \
  tests/materializer/test_synthesis.py::test_materialize_one_asset_uses_mkvmerge_final_invocation_for_profile \
  -q
```

Expected: imports/functions do not exist yet.

- [ ] **Step 4: Implement mkvmerge tooling**

Create `src/chaos_librarian/materializer/tooling/mkvmerge.py`:

```python
from __future__ import annotations

import subprocess
import time
from pathlib import Path

from chaos_librarian.contract.materialization import ToolInvocation
from chaos_librarian.contract.scenario import MatroskaMuxingProfile


def build_mkvmerge_command(
    *,
    input_path: Path,
    output_path: Path,
    container: str,
    profile: MatroskaMuxingProfile,
    deterministic_seed: int,
) -> list[str]:
    argv = [
        "mkvmerge",
        "--quiet",
        "--deterministic",
        str(deterministic_seed),
        "--no-date",
        "--disable-track-statistics-tags",
    ]
    if container == "webm":
        argv.append("--webm")
    if profile is MatroskaMuxingProfile.NO_CUES:
        argv.append("--no-cues")
    elif profile is MatroskaMuxingProfile.DENSE_CUES:
        argv.extend(["--cues", "0:all"])
    elif profile is MatroskaMuxingProfile.SHORT_CLUSTERS:
        argv.extend(["--cluster-length", "250ms"])
    argv.extend(["-o", str(output_path), str(input_path)])
    return argv


def run_mkvmerge(
    argv: list[str],
    *,
    mkvmerge_version: str,
    timeout_s: float = 60.0,
) -> tuple[ToolInvocation, str]:
    start = time.monotonic_ns()
    completed = subprocess.run(
        argv,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        timeout=timeout_s,
        check=False,
        stdin=subprocess.DEVNULL,
    )
    stderr_tail = (completed.stderr or b"")[-2048:].decode("utf-8", errors="replace")
    return (
        ToolInvocation(
            tool="mkvmerge",
            version=mkvmerge_version,
            command=list(argv),
            exit_code=completed.returncode,
            duration_ns=time.monotonic_ns() - start,
        ),
        stderr_tail,
    )
```

- [ ] **Step 5: Implement muxing source evidence**

In `content_sources.py`, add:

```python
MUXING_PROVIDER_NAME: Final = "builtin-mkvmerge"

@dataclass(frozen=True, slots=True)
class MuxingSourceRequest:
    asset_id: str
    seed: int
    container: str
    profile: MatroskaMuxingProfile

@dataclass(frozen=True, slots=True)
class MuxingSourceResolution:
    deterministic_seed: int
    evidence: ContentSourceEvidence
```

Add:

```python
def resolve_muxing_source(request: MuxingSourceRequest) -> MuxingSourceResolution:
    deterministic_seed = _muxing_deterministic_seed(request)
    evidence = ContentSourceEvidence(
        asset_id=request.asset_id,
        track_kind=ContentTrackKind.MUXING,
        source=request.profile.value,
        provider=MUXING_PROVIDER_NAME,
        recipe_digest=_muxing_recipe_digest(request=request, deterministic_seed=deterministic_seed),
        matroska_muxing_profile=request.profile,
        container=request.container,
        cache_disposition=CacheDisposition.NOT_CACHEABLE,
    )
    return MuxingSourceResolution(deterministic_seed=deterministic_seed, evidence=evidence)
```

Implement `_muxing_deterministic_seed` with `int(_sha256_hex(payload)[:8], 16)`.

- [ ] **Step 6: Thread synthesis**

In `synthesis.py`, import `build_mkvmerge_command`, `run_mkvmerge`, `MuxingSourceRequest`, and `resolve_muxing_source`.

Inside `materialize_one_asset`, when `asset.matroska_muxing_profile is not None`, set `ffmpeg_output_path = temp_path / f"media.{asset.container}"`; otherwise use `output_path`.

After FFmpeg succeeds, if a profile exists:

```python
muxing_resolution = resolve_muxing_source(
    MuxingSourceRequest(
        asset_id=asset.id,
        seed=seed,
        container=asset.container,
        profile=asset.matroska_muxing_profile,
    )
)
content_sources = (*content_sources, muxing_resolution.evidence)
mkvmerge_argv = build_mkvmerge_command(
    input_path=ffmpeg_output_path,
    output_path=output_path,
    container=asset.container,
    profile=asset.matroska_muxing_profile,
    deterministic_seed=muxing_resolution.deterministic_seed,
)
mkvmerge_invocation, stderr_tail = run_mkvmerge(
    mkvmerge_argv,
    mkvmerge_version=caps.mkvtoolnix.version or "unknown",
)
if mkvmerge_invocation.exit_code != 0:
    raise _tool_failed(
        asset=asset,
        invocation=mkvmerge_invocation,
        stderr_tail=stderr_tail,
        content_sources=content_sources,
    )
prelude_invocations = (*embedded_inputs.prelude_invocations, invocation)
invocation = mkvmerge_invocation
```

Keep the current direct FFmpeg path unchanged for assets without a profile.
Change `_tool_failed` message to use `invocation.tool` instead of hard-coded `ffmpeg`.

- [ ] **Step 7: Run green tests and commit**

Run:

```bash
uv run pytest --no-cov \
  tests/materializer/test_mkvmerge_builder.py \
  tests/materializer/test_content_sources.py \
  tests/materializer/test_synthesis.py \
  -q
uv run ruff check src/chaos_librarian/materializer tests/materializer
```

Commit:

```bash
git add src/chaos_librarian/materializer tests/materializer
git commit -m "Materialize muxing profiles with mkvmerge"
```

---

### Task 5: Real Smoke Tests, Schemas, Docs, and Verification

**Files:**
- Add: `tests/materializer/test_muxing_profiles_real.py`
- Modify: `docs/contract/schema-reference.md`
- Modify: `schemas/*.schema.json`
- Modify version literals in test fixtures and helper YAML snippets from `schema_version: 21` to `22`.

- [ ] **Step 1: Write real smoke tests**

Create `tests/materializer/test_muxing_profiles_real.py`:

```python
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from chaos_librarian.contract.scenario import Asset, MatroskaMuxingProfile, VideoSource, VideoTrack
from chaos_librarian.materializer.synthesis import materialize_one_asset

pytestmark = pytest.mark.skipif(
    any(shutil.which(tool) is None for tool in ("ffmpeg", "ffprobe", "mkvmerge", "mkvinfo")),
    reason="ffmpeg, ffprobe, mkvmerge, and mkvinfo are required for muxing profile smoke tests",
)


def test_materialize_mkv_no_cues_removes_cues(tmp_path: Path) -> None:
    result = materialize_one_asset(
        _asset(MatroskaMuxingProfile.NO_CUES),
        138,
        tmp_path / "run",
        _caps(),
        0,
        rendered_relative_path="r/A.mkv",
    )
    info = _mkvinfo(tmp_path / "run/library/r/A.mkv")
    assert "+ Cues" not in info
    assert "(KaxCues)" not in info
    assert any(source.source == "no_cues" for source in result.content_sources)


def test_materialize_mkv_dense_cues_writes_multiple_cue_points(tmp_path: Path) -> None:
    materialize_one_asset(_asset(MatroskaMuxingProfile.DENSE_CUES), 138, tmp_path / "run", _caps(), 0, rendered_relative_path="r/A.mkv")
    assert _mkvinfo(tmp_path / "run/library/r/A.mkv").count("+ Cue point") > 1


def test_materialize_mkv_short_clusters_writes_multiple_clusters(tmp_path: Path) -> None:
    materialize_one_asset(_asset(MatroskaMuxingProfile.SHORT_CLUSTERS), 138, tmp_path / "run", _caps(), 0, rendered_relative_path="r/A.mkv")
    assert _top_level_cluster_count(_mkvinfo(tmp_path / "run/library/r/A.mkv")) > 1


def test_materialize_webm_short_clusters_is_probe_visible(tmp_path: Path) -> None:
    asset = _asset(MatroskaMuxingProfile.SHORT_CLUSTERS, container="webm", codec="vp9")
    result = materialize_one_asset(asset, 138, tmp_path / "run", _caps(), 0, rendered_relative_path="r/A.webm")
    assert result.probed.container == "matroska,webm"
    assert result.probed.streams[0].codec == "vp9"
    assert _top_level_cluster_count(_mkvinfo(tmp_path / "run/library/r/A.webm")) > 1
```

Add local helpers `_asset`, `_caps`, `_mkvinfo`, and `_top_level_cluster_count`. `_asset` should create a video-only one-second asset by default so cluster counts are deterministic. `_caps` should set both new readiness flags true and mkvtoolnix found true.

- [ ] **Step 2: Run smoke tests red/green**

Run the smoke tests. If implementation is complete, they should pass; if not, debug with `superpowers:systematic-debugging`.

```bash
uv run pytest --no-cov tests/materializer/test_muxing_profiles_real.py -q
```

- [ ] **Step 3: Regenerate schemas and update docs**

Run:

```bash
uv run python -m chaos_librarian.schema_export --write
```

Update `docs/contract/schema-reference.md` current table:

- scenario `22`
- replay bundle `12`
- materialization `15`
- capabilities `7`

Add a changelog paragraph before Scenario v21:

```markdown
Scenario v22 adds `matroska_muxing_profile` for MKV/WebM cue and cluster
profiles. Capabilities v7 reports readiness for mkvmerge-backed muxing
profiles and minimal WebM VP9 synthesis. Materialization v15 and replay-bundle
v12 carry selected muxing profile evidence.
```

Bulk-update current scenario fixture/test snippets:

```bash
rg --files tests src -g '*.py' -g '*.yaml' | xargs perl -0pi -e 's/schema_version: 21/schema_version: 22/g; s/schema_version=21/schema_version=22/g; s/"schema_version": 21/"schema_version": 22/g'
```

Manually review the diff to ensure historical docs or intentionally invalid version tests were not changed incorrectly.

- [ ] **Step 4: Run schema/version verification**

Run:

```bash
uv run python -m chaos_librarian.schema_export --check
uv run pytest --no-cov tests/contract/test_schema_export.py tests/contract/test_contract_constants.py -q
uv run ruff check docs/contract/schema-reference.md tests/materializer/test_muxing_profiles_real.py
```

Expected: schemas up to date, tests pass, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add docs/contract/schema-reference.md schemas tests src
git commit -m "Regenerate schemas for muxing profiles"
```

---

### Task 6: Final Review, Simplification, PR, and Merge

**Files:**
- Entire branch diff against `origin/main`

- [ ] **Step 1: Run adversarial code review**

Review:

```bash
git diff origin/main...HEAD
```

Use `superpowers:adversarial-review`. Address material findings. Run no more than three adversarial code review passes for this implementation cycle.

- [ ] **Step 2: Run simplification review**

Use `simplification-review` on the branch diff. Address only simplifications that reduce risk without widening scope.

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
git push -u origin feat/issue-138-mkv-webm-muxing-profiles
gh pr create --base main --head feat/issue-138-mkv-webm-muxing-profiles \
  --title "Add MKV and WebM muxing profiles" \
  --body "Closes #138"
```

Include verification commands and review notes in the PR body.

- [ ] **Step 5: Monitor, merge, and confirm closure**

```bash
gh pr checks <PR_NUMBER> --watch --interval 10
gh pr merge <PR_NUMBER> --merge --delete-branch --repo randomparity/chaos-librarian
gh issue view 138 --repo randomparity/chaos-librarian --json state,closedAt,url
```

Expected: PR merged, issue #138 closed.
