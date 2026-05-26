# Issue 106 Materializer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish Issue 106 materializer support for hierarchy scenarios: audio-only track assets, rendered Phase-A paths, hierarchy Phase-B moves, and materializer-owned fixture conversion away from `works`.

**Architecture:** Keep validation as the first policy gate, but make materializer preflight and synthesis enforce the same parent-kind media matrix defensively. Continue treating the engine journal as the Phase-B source of truth: hierarchy filesystem changes come from `state_delta.path_moves` and `state_delta.sidecar_moves`, not from recomputing paths in the materializer. Preserve existing video synthesis behavior and add an audio-only branch rather than generalizing video code prematurely.

**Tech Stack:** Python 3.13, Pydantic v2, pytest, ruff, ty, FFmpeg/ffprobe materializer.

---

## Context

The parent plan is `docs/superpowers/plans/2026-05-26-issue-106-media-hierarchies.md`.
Contract/renderer, validation, and engine/reports slices have already landed.

Current materializer state:

- `materialize_assets_phase_a()` already iterates `AssetContext` and passes a
  rendered hierarchy path into `materialize_one_asset()`.
- Audio-only constants exist in `media_matrix.py`, but `preflight_asset()`,
  `build_command()`, and `materialize_one_asset()` still require video.
- Hierarchy actions are not in the materializer supported action set and
  filesystem Phase B does not yet read hierarchy `path_moves` / `sidecar_moves`.
- Some materializer-owned tests and voom-ci fixtures still use `schema_version:
  11` with `works:`.

## Files

- Create: `tests/materializer/test_audio_only.py`
- Create: `tests/materializer/test_hierarchy_moves.py`
- Modify: `src/chaos_librarian/media_matrix.py`
- Modify: `src/chaos_librarian/materializer/actions.py`
- Modify: `src/chaos_librarian/materializer/preflight.py`
- Modify: `src/chaos_librarian/materializer/run.py`
- Modify: `src/chaos_librarian/materializer/replay.py`
- Modify: `src/chaos_librarian/materializer/wall_clock.py`
- Modify: `src/chaos_librarian/materializer/synthesis.py`
- Modify: `src/chaos_librarian/materializer/tooling/ffmpeg.py`
- Modify: `src/chaos_librarian/materializer/phase_b/filesystem.py`
- Modify: `tests/materializer/test_actions.py`
- Modify: `tests/materializer/test_content_sources.py`
- Modify: `tests/materializer/test_ffmpeg_builder.py`
- Modify: `tests/materializer/test_filesystem.py`
- Modify: `tests/materializer/test_preflight.py`
- Modify: `tests/materializer/test_run.py`
- Modify: `tests/materializer/test_run_sprint7.py`
- Modify: `tests/materializer/test_synthesis.py`
- Modify: `tests/fixtures/scenarios/voom-ci/*.yaml`

## Task 1: Audio-Only Preflight Policy

**Files:**
- Create: `tests/materializer/test_audio_only.py`
- Modify: `src/chaos_librarian/materializer/preflight.py`
- Modify: `src/chaos_librarian/materializer/run.py`
- Modify: `src/chaos_librarian/materializer/replay.py`
- Modify: `src/chaos_librarian/materializer/wall_clock.py`
- Modify: `tests/materializer/test_content_sources.py`

- [ ] **Step 1: Add failing preflight tests**

Create `tests/materializer/test_audio_only.py` with the preflight tests below.
These tests call `preflight_asset()` directly because this task is only about
the materializer's static media policy gate.

```python
"""Audio-only materializer coverage for track assets."""

from __future__ import annotations

import pytest

from chaos_librarian.contract.domain import ParentKind
from chaos_librarian.contract.scenario import (
    AudioChannelLayout,
    AudioSource,
    AudioTrack,
    SubtitleMode,
    SubtitleTrack,
    VideoSource,
    VideoTrack,
)
from chaos_librarian.materializer.errors import UnsupportedMaterializationError
from chaos_librarian.materializer.preflight import preflight_asset


def _audio(codec: str) -> AudioTrack:
    return AudioTrack(
        source=AudioSource.SINE,
        codec=codec,
        channels=AudioChannelLayout.STEREO,
        language="eng",
    )


def _video() -> VideoTrack:
    return VideoTrack(source=VideoSource.COLOR_BARS, codec="h264", resolution="hd")


@pytest.mark.parametrize(
    ("container", "codec"),
    [("flac", "flac"), ("mp3", "mp3"), ("m4a", "aac")],
)
def test_track_audio_only_cells_pass_preflight(container: str, codec: str) -> None:
    preflight_asset(
        parent_kind=ParentKind.TRACK,
        video=None,
        audios=[_audio(codec)],
        subtitles=[],
        container=container,
    )


def test_track_with_video_rejected_by_preflight() -> None:
    with pytest.raises(UnsupportedMaterializationError) as exc_info:
        preflight_asset(
            parent_kind=ParentKind.TRACK,
            video=_video(),
            audios=[_audio("flac")],
            subtitles=[],
            container="flac",
        )

    assert exc_info.value.field == "video"


def test_track_with_subtitle_rejected_by_preflight() -> None:
    subtitle = SubtitleTrack(codec="srt", language="eng", mode=SubtitleMode.SIDECAR)

    with pytest.raises(UnsupportedMaterializationError) as exc_info:
        preflight_asset(
            parent_kind=ParentKind.TRACK,
            video=None,
            audios=[_audio("flac")],
            subtitles=[subtitle],
            container="flac",
        )

    assert exc_info.value.field == "subtitles"


@pytest.mark.parametrize(
    ("container", "codec", "field"),
    [("mkv", "flac", "container"), ("flac", "aac", "audio[0].codec")],
)
def test_track_unsupported_audio_only_cell_rejected(
    container: str, codec: str, field: str
) -> None:
    with pytest.raises(UnsupportedMaterializationError) as exc_info:
        preflight_asset(
            parent_kind=ParentKind.TRACK,
            video=None,
            audios=[_audio(codec)],
            subtitles=[],
            container=container,
        )

    assert exc_info.value.field == field


@pytest.mark.parametrize("parent_kind", [ParentKind.MOVIE, ParentKind.EPISODE])
def test_video_parent_without_video_rejected(parent_kind: ParentKind) -> None:
    with pytest.raises(UnsupportedMaterializationError) as exc_info:
        preflight_asset(
            parent_kind=parent_kind,
            video=None,
            audios=[_audio("aac")],
            subtitles=[],
            container="mkv",
        )

    assert exc_info.value.field == "video"
```

- [ ] **Step 2: Run tests to verify RED**

```bash
uv run pytest tests/materializer/test_audio_only.py -q --no-cov
```

Expected: import or call failures because `preflight_asset()` does not accept
`parent_kind`, then audio-only rejection failures after the signature is updated
but before implementation.

- [ ] **Step 3: Implement parent-kind aware preflight**

In `src/chaos_librarian/materializer/preflight.py`:

- Import `ParentKind` and `SUPPORTED_AUDIO_ONLY_CODECS_BY_CONTAINER`.
- Change `preflight_asset()` to keyword-only arguments:

```python
def preflight_asset(
    *,
    parent_kind: ParentKind,
    video: VideoTrack | None,
    audios: Sequence[AudioTrack],
    subtitles: Sequence[SubtitleTrack],
    container: str,
) -> None:
```

- For `ParentKind.TRACK`:
  - reject `video is not None` with `field="video"`;
  - reject any subtitles with `field="subtitles"`;
  - require exactly one audio stream with `field="audio"`;
  - require `container` in `SUPPORTED_AUDIO_ONLY_CODECS_BY_CONTAINER` with
    `field="container"`;
  - require the single audio codec in that container's supported set with
    `field="audio[0].codec"`;
  - call `build_command(video=None, video_input=None, ...)` after building the
    audio input to keep recipe/source validation aligned with synthesis.
- For `ParentKind.MOVIE` and `ParentKind.EPISODE`, keep existing video behavior:
  require `video`, preflight subtitles, resolve video/audio inputs, then call
  `build_command(video=video, video_input=video_input, ...)`.

- [ ] **Step 4: Update preflight call sites**

In `src/chaos_librarian/materializer/run.py`,
`src/chaos_librarian/materializer/replay.py`, and
`src/chaos_librarian/materializer/wall_clock.py`, replace loops like:

```python
for asset in iter_assets(scenario):
    preflight_asset(asset.video, asset.audio, asset.subtitles, asset.container)
```

with:

```python
for context in iter_asset_contexts(scenario):
    asset = context.asset
    preflight_asset(
        parent_kind=context.parent_kind,
        video=asset.video,
        audios=asset.audio,
        subtitles=asset.subtitles,
        container=asset.container,
    )
```

Import `iter_asset_contexts` from `chaos_librarian.topology` in those modules.
Keep `iter_assets()` available for existing HEVC and manifest stamping loops.

Update `tests/materializer/test_content_sources.py` to call:

```python
preflight_asset(
    parent_kind=ParentKind.MOVIE,
    video=_video(),
    audios=[_audio()],
    subtitles=[],
    container="mkv",
)
```

- [ ] **Step 5: Verify and commit**

```bash
uv run pytest tests/materializer/test_audio_only.py tests/materializer/test_content_sources.py -q --no-cov
uv run ruff check src/chaos_librarian/materializer/preflight.py src/chaos_librarian/materializer/run.py src/chaos_librarian/materializer/replay.py src/chaos_librarian/materializer/wall_clock.py tests/materializer/test_audio_only.py tests/materializer/test_content_sources.py
uv run ruff format --check src/chaos_librarian/materializer/preflight.py src/chaos_librarian/materializer/run.py src/chaos_librarian/materializer/replay.py src/chaos_librarian/materializer/wall_clock.py tests/materializer/test_audio_only.py tests/materializer/test_content_sources.py
git add src/chaos_librarian/materializer/preflight.py src/chaos_librarian/materializer/run.py src/chaos_librarian/materializer/replay.py src/chaos_librarian/materializer/wall_clock.py tests/materializer/test_audio_only.py tests/materializer/test_content_sources.py
git commit -m "feat: preflight audio-only track assets"
```

## Task 2: Audio-Only FFmpeg and Synthesis

**Files:**
- Modify: `src/chaos_librarian/media_matrix.py`
- Modify: `src/chaos_librarian/materializer/tooling/ffmpeg.py`
- Modify: `src/chaos_librarian/materializer/synthesis.py`
- Modify: `tests/materializer/test_ffmpeg_builder.py`
- Modify: `tests/materializer/test_synthesis.py`
- Modify: `tests/materializer/test_audio_only.py`

- [ ] **Step 1: Add failing FFmpeg argv tests**

In `tests/materializer/test_ffmpeg_builder.py`, update `_audio()` to accept a
codec argument:

```python
def _audio(
    channels: AudioChannelLayout = AudioChannelLayout.STEREO,
    *,
    codec: str = "aac",
) -> AudioTrack:
    return AudioTrack(source=AudioSource.SINE, codec=codec, channels=channels, language="eng")
```

Then add:

```python
@pytest.mark.parametrize(
    ("container", "codec", "encoder"),
    [("flac", "flac", "flac"), ("mp3", "mp3", "libmp3lame"), ("m4a", "aac", "aac")],
)
def test_audio_only_command_maps_audio_without_video_codec(
    container: str, codec: str, encoder: str, tmp_path: Path
) -> None:
    output = tmp_path / f"asset.{container}"

    argv = build_command(
        video=None,
        video_input=None,
        audios=[_audio(codec=codec)],
        audio_inputs=[recipe_sine(channels="stereo", duration_s=1.0, seed=1)],
        output_path=output,
    )

    assert argv[0] == "ffmpeg"
    assert "-c:v" not in argv
    assert [argv[index + 1] for index, arg in enumerate(argv) if arg == "-map"] == ["0:a:0"]
    assert argv[argv.index("-c:a") + 1] == encoder
    for flag in BITEXACT_FLAGS:
        assert flag in argv
    assert argv[-1] == str(output)


def test_audio_only_command_rejects_wrong_codec_for_container(tmp_path: Path) -> None:
    with pytest.raises(UnsupportedMaterializationError) as exc_info:
        build_command(
            video=None,
            video_input=None,
            audios=[_audio(codec="aac")],
            audio_inputs=[recipe_sine(channels="stereo", duration_s=1.0, seed=1)],
            output_path=tmp_path / "asset.flac",
        )

    assert exc_info.value.field == "audio[0].codec"
```

- [ ] **Step 2: Add failing synthesis test**

In `tests/materializer/test_synthesis.py`, add:

```python
def test_materialize_one_asset_writes_audio_only_track(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    asset = _track_audio_asset(container="flac", codec="flac")
    output_path = tmp_path / "run" / "library" / "music" / "Artist" / "Album" / "01 - Song.flac"

    def fake_run_ffmpeg(argv: list[str], *, ffmpeg_version: str, timeout_s: float = 60.0):
        del timeout_s
        Path(argv[-1]).write_bytes(b"audio")
        return (
            ToolInvocation(
                tool="ffmpeg",
                version=ffmpeg_version,
                command=argv,
                exit_code=0,
                duration_ns=1,
            ),
            "",
        )

    monkeypatch.setattr(synthesis_mod, "run_ffmpeg", fake_run_ffmpeg)
    monkeypatch.setattr(
        synthesis_mod,
        "probe_file",
        lambda _path: ProbedMedia(
            container="flac",
            duration_seconds=1,
            size_bytes=output_path.stat().st_size,
            streams=[ProbedStream(kind=StreamKind.AUDIO, codec="flac", channels=2)],
        ),
    )

    result = materialize_one_asset(
        asset,
        1,
        tmp_path / "run",
        _caps(),
        0,
        rendered_relative_path="music/Artist/Album/01 - Song.flac",
    )

    assert result.materialized_asset.location_path == "library/music/Artist/Album/01 - Song.flac"
    assert output_path.read_bytes() == b"audio"
    assert [evidence.track_kind for evidence in result.content_sources] == [
        ContentTrackKind.AUDIO
    ]
    assert result.sidecar_hashes == {}


def _track_audio_asset(*, container: str, codec: str):
    scenario = prepare_run_input_from_bytes(
        raw_bytes=f"""\
schema_version: 12
scenario_id: audio-only-materialize
seed: 1
duration_scale: short
library:
  roots:
    - id: music
      path: music
movies: []
series: []
artists:
  - id: artist_1
    name: Artist
    layout: artist_album_disc
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
                title: Song
                variants:
                  - id: variant_1
                    label: lossless
                    bundle:
                      id: bundle_1
                      assets:
                        - id: asset_track
                          role: audio
                          container: {container}
                          duration_seconds: 1
                          audio:
                            - source: sine
                              codec: {codec}
                              channels: stereo
                              language: eng
timeline: []
""".encode(),
        source_label="test:audio-only-materialize.yaml",
    ).scenario
    return scenario.artists[0].albums[0].discs[0].tracks[0].variants[0].bundle.assets[0]
```

- [ ] **Step 3: Run tests to verify RED**

```bash
uv run pytest tests/materializer/test_ffmpeg_builder.py::test_audio_only_command_maps_audio_without_video_codec tests/materializer/test_ffmpeg_builder.py::test_audio_only_command_rejects_wrong_codec_for_container tests/materializer/test_synthesis.py::test_materialize_one_asset_writes_audio_only_track -q --no-cov
```

Expected: failures because `build_command()` and `materialize_one_asset()` still
require video.

- [ ] **Step 4: Implement audio-only argv**

In `src/chaos_librarian/media_matrix.py`, add:

```python
AUDIO_ENCODER_BY_CODEC: Final[dict[str, str]] = {
    "aac": "aac",
    "flac": "flac",
    "mp3": "libmp3lame",
}
```

In `src/chaos_librarian/materializer/tooling/ffmpeg.py`:

- Add `.flac`, `.mp3`, and `.m4a` to `_CONTAINER_FROM_EXTENSION`.
- Import `AUDIO_ENCODER_BY_CODEC`, `SUPPORTED_AUDIO_ONLY_CODECS_BY_CONTAINER`,
  and `SUPPORTED_VIDEO_CONTAINERS`.
- Change `build_command()` to:

```python
def build_command(
    *,
    video: VideoTrack | None,
    video_input: FFmpegInput | None,
    audios: Sequence[AudioTrack],
    audio_inputs: Sequence[FFmpegInput],
    output_path: Path,
) -> list[str]:
```

- For video assets, require `video_input is not None`, require the resolved
  container in `SUPPORTED_VIDEO_CONTAINERS`, validate video, map `0:v:0`, map
  audio inputs starting at input index `1`, and emit `-c:v`.
- For audio-only assets, require `video_input is None`, require the resolved
  container in `SUPPORTED_AUDIO_ONLY_CODECS_BY_CONTAINER`, map audio inputs
  starting at input index `0`, and do not emit `-c:v`.
- For audio-only assets, validate every audio codec against the selected
  container's codec set.
- Use `AUDIO_ENCODER_BY_CODEC[audios[0].codec]` for `-c:a` when only one audio
  stream is present. Keep existing `aac` encoding for video assets.
- Keep `BITEXACT_FLAGS` and `-shortest` in both branches.

- [ ] **Step 5: Implement audio-only synthesis**

In `src/chaos_librarian/materializer/synthesis.py`, remove the unconditional
`asset.video is None` rejection. Build video input/content evidence only when
`asset.video is not None`; always resolve audio inputs/content evidence. Call:

```python
argv = build_command(
    video=asset.video,
    video_input=video_input,
    audios=asset.audio,
    audio_inputs=audio_inputs,
    output_path=output_path,
)
```

where `video_input` is `None` for audio-only assets. Do not write declared
sidecars for track assets; validation rejects them and `write_sidecars()` will
return `{}`.

- [ ] **Step 6: Verify and commit**

```bash
uv run pytest tests/materializer/test_audio_only.py tests/materializer/test_ffmpeg_builder.py tests/materializer/test_synthesis.py -q --no-cov
uv run ruff check src/chaos_librarian/media_matrix.py src/chaos_librarian/materializer/tooling/ffmpeg.py src/chaos_librarian/materializer/synthesis.py tests/materializer/test_audio_only.py tests/materializer/test_ffmpeg_builder.py tests/materializer/test_synthesis.py
uv run ruff format --check src/chaos_librarian/media_matrix.py src/chaos_librarian/materializer/tooling/ffmpeg.py src/chaos_librarian/materializer/synthesis.py tests/materializer/test_audio_only.py tests/materializer/test_ffmpeg_builder.py tests/materializer/test_synthesis.py
git add src/chaos_librarian/media_matrix.py src/chaos_librarian/materializer/tooling/ffmpeg.py src/chaos_librarian/materializer/synthesis.py tests/materializer/test_audio_only.py tests/materializer/test_ffmpeg_builder.py tests/materializer/test_synthesis.py
git commit -m "feat: synthesize audio-only track assets"
```

## Task 3: Hierarchy Phase-B Filesystem Moves

**Files:**
- Create: `tests/materializer/test_hierarchy_moves.py`
- Modify: `src/chaos_librarian/materializer/actions.py`
- Modify: `src/chaos_librarian/materializer/phase_b/filesystem.py`
- Modify: `tests/materializer/test_actions.py`
- Modify: `tests/materializer/test_preflight.py`

- [ ] **Step 1: Add failing hierarchy action-set tests**

In `tests/materializer/test_actions.py`, import `_HIERARCHY_ACTIONS` and add:

```python
def test_supported_s10_actions_include_hierarchy_filesystem_actions() -> None:
    expected = frozenset(
        {
            TimelineActionName.RENUMBER_EPISODE,
            TimelineActionName.MOVE_EPISODE_TO_SEASON,
            TimelineActionName.RENAME_SEASON,
            TimelineActionName.RENUMBER_DISC,
            TimelineActionName.MOVE_TRACK_TO_DISC,
        }
    )
    assert _HIERARCHY_ACTIONS == expected
    assert expected <= SUPPORTED_S10_ACTIONS
```

In `tests/materializer/test_preflight.py`, add:

```python
@pytest.mark.parametrize(
    ("action_name", "extra_fields"),
    [
        ("renumber_episode", {"episode_number": 2}),
        ("move_episode_to_season", {"to_season": "season_2", "episode_number": 1}),
        ("rename_season", {"title": "Renamed"}),
        ("renumber_disc", {"disc_number": 2}),
        ("move_track_to_disc", {"to_disc": "disc_2", "track_number": 3}),
    ],
)
def test_preflight_timeline_accepts_hierarchy_actions(
    action_name: str, extra_fields: dict[str, object]
) -> None:
    scenario = _scenario_with_timeline([(action_name, "hierarchy_target", extra_fields)])
    preflight_timeline(scenario)
```

- [ ] **Step 2: Add failing filesystem hierarchy move tests**

Create `tests/materializer/test_hierarchy_moves.py`:

```python
"""Phase-B materializer support for hierarchy journal path moves."""

from __future__ import annotations

from pathlib import Path

import pytest

from chaos_librarian.contract.journal import JournalEntry
from chaos_librarian.contract.materialization import FilesystemAction
from chaos_librarian.contract.scenario import TimelineActionName
from chaos_librarian.materializer.errors import FilesystemActionError
from chaos_librarian.materializer.phase_b.filesystem import (
    apply_filesystem_action,
    make_filesystem_phase_b_context,
)
from tests.materializer.test_filesystem import _scenario, _scenario_assets
from tests.materializer.conftest import _atomic_entry


def _apply(library: Path, entry: JournalEntry) -> FilesystemAction | None:
    ctx = make_filesystem_phase_b_context(
        library_root=library,
        scenario_assets=_scenario_assets(_scenario()),
        resolved_seed=1234,
    )
    return apply_filesystem_action(ctx, entry)


def test_hierarchy_move_rejects_destination_occupied_outside_move_set(tmp_path: Path) -> None:
    library = tmp_path / "library"
    (library / "tv").mkdir(parents=True)
    source = library / "tv" / "Show - S01E01.mkv"
    occupied = library / "tv" / "Show - S01E02.mkv"
    source.write_bytes(b"source")
    occupied.write_bytes(b"occupied")
    entry = _atomic_entry(
        event_id="renumber_001",
        action=TimelineActionName.RENUMBER_EPISODE,
        target="episode_1",
        state_delta={
            "metadata": {"episode_number": {"before": 1, "after": 2}},
            "path_moves": [
                {
                    "asset_id": "asset_hd_main",
                    "location_id": "location_0001",
                    "from_path": "tv/Show - S01E01.mkv",
                    "to_path": "tv/Show - S01E02.mkv",
                }
            ],
            "sidecar_moves": [],
            "skipped_deleted_asset_ids": [],
        },
    )

    with pytest.raises(FilesystemActionError):
        _apply(library, entry)

    assert source.read_bytes() == b"source"
    assert occupied.read_bytes() == b"occupied"


def test_hierarchy_move_swaps_paths_via_temporary_siblings(tmp_path: Path) -> None:
    library = tmp_path / "library"
    (library / "music").mkdir(parents=True)
    first = library / "music" / "01 - First.flac"
    second = library / "music" / "02 - Second.flac"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    entry = _atomic_entry(
        event_id="renumber_disc_001",
        action=TimelineActionName.RENUMBER_DISC,
        target="disc_1",
        state_delta={
            "metadata": {"disc_number": {"before": 1, "after": 2}},
            "path_moves": [
                {
                    "asset_id": "asset_first",
                    "location_id": "location_0001",
                    "from_path": "music/01 - First.flac",
                    "to_path": "music/02 - Second.flac",
                },
                {
                    "asset_id": "asset_second",
                    "location_id": "location_0002",
                    "from_path": "music/02 - Second.flac",
                    "to_path": "music/01 - First.flac",
                },
            ],
            "sidecar_moves": [],
            "skipped_deleted_asset_ids": [],
        },
    )

    action = _apply(library, entry)

    assert action is not None
    assert first.read_bytes() == b"second"
    assert second.read_bytes() == b"first"
    assert list((library / "music").glob("*.tmp")) == []


def test_hierarchy_move_moves_renderer_derived_sidecar(tmp_path: Path) -> None:
    library = tmp_path / "library"
    (library / "tv").mkdir(parents=True)
    media = library / "tv" / "Show - S01E01.mkv"
    sidecar = library / "tv" / "Show - S01E01.eng.srt"
    media.write_bytes(b"media")
    sidecar.write_bytes(b"subtitle")
    entry = _atomic_entry(
        event_id="renumber_001",
        action=TimelineActionName.RENUMBER_EPISODE,
        target="episode_1",
        state_delta={
            "metadata": {"episode_number": {"before": 1, "after": 2}},
            "path_moves": [
                {
                    "asset_id": "asset_hd_main",
                    "location_id": "location_0001",
                    "from_path": "tv/Show - S01E01.mkv",
                    "to_path": "tv/Show - S01E02.mkv",
                }
            ],
            "sidecar_moves": [
                {
                    "sidecar_id": "sidecar_asset_hd_main_eng",
                    "asset_id": "asset_hd_main",
                    "from_path": "tv/Show - S01E01.eng.srt",
                    "to_path": "tv/Show - S01E02.eng.srt",
                }
            ],
            "skipped_deleted_asset_ids": [],
        },
    )

    _apply(library, entry)

    assert not media.exists()
    assert not sidecar.exists()
    assert (library / "tv" / "Show - S01E02.mkv").read_bytes() == b"media"
    assert (library / "tv" / "Show - S01E02.eng.srt").read_bytes() == b"subtitle"


def test_hierarchy_move_leaves_explicit_timeline_sidecar_in_place(tmp_path: Path) -> None:
    library = tmp_path / "library"
    (library / "tv").mkdir(parents=True)
    (library / "custom").mkdir(parents=True)
    media = library / "tv" / "Show - S01E01.mkv"
    explicit = library / "custom" / "spanish.srt"
    media.write_bytes(b"media")
    explicit.write_bytes(b"explicit")
    entry = _atomic_entry(
        event_id="renumber_001",
        action=TimelineActionName.RENUMBER_EPISODE,
        target="episode_1",
        state_delta={
            "metadata": {"episode_number": {"before": 1, "after": 2}},
            "path_moves": [
                {
                    "asset_id": "asset_hd_main",
                    "location_id": "location_0001",
                    "from_path": "tv/Show - S01E01.mkv",
                    "to_path": "tv/Show - S01E02.mkv",
                }
            ],
            "sidecar_moves": [],
            "skipped_deleted_asset_ids": [],
        },
    )

    _apply(library, entry)

    assert (library / "tv" / "Show - S01E02.mkv").read_bytes() == b"media"
    assert explicit.read_bytes() == b"explicit"


def test_hierarchy_entry_with_no_moves_is_noop(tmp_path: Path) -> None:
    library = tmp_path / "library"
    library.mkdir()
    entry = _atomic_entry(
        event_id="rename_season_001",
        action=TimelineActionName.RENAME_SEASON,
        target="season_1",
        state_delta={
            "metadata": {"title": {"before": "Old", "after": "New"}},
            "path_moves": [],
            "sidecar_moves": [],
            "skipped_deleted_asset_ids": [],
        },
    )

    assert _apply(library, entry) is None
```

- [ ] **Step 3: Run tests to verify RED**

```bash
uv run pytest tests/materializer/test_actions.py::test_supported_s10_actions_include_hierarchy_filesystem_actions tests/materializer/test_preflight.py::test_preflight_timeline_accepts_hierarchy_actions tests/materializer/test_hierarchy_moves.py -q --no-cov
```

Expected: failures because hierarchy actions are not supported and there is no
filesystem handler.

- [ ] **Step 4: Add hierarchy action set**

In `src/chaos_librarian/materializer/actions.py`, add:

```python
_HIERARCHY_ACTIONS: Final[frozenset[TimelineActionName]] = frozenset(
    {
        TimelineActionName.RENUMBER_EPISODE,
        TimelineActionName.MOVE_EPISODE_TO_SEASON,
        TimelineActionName.RENAME_SEASON,
        TimelineActionName.RENUMBER_DISC,
        TimelineActionName.MOVE_TRACK_TO_DISC,
    }
)
```

Include `_HIERARCHY_ACTIONS` in `SUPPORTED_S10_ACTIONS`. Treat these as
filesystem actions; do not route them through media handlers.

- [ ] **Step 5: Implement one hierarchy filesystem handler**

In `src/chaos_librarian/materializer/phase_b/filesystem.py`:

- Add a `_hierarchy_moves()` handler and route every hierarchy action in
  `_DISPATCH` to it.
- Read `state_delta["path_moves"]` and `state_delta["sidecar_moves"]`.
- Normalize both lists into `(asset_id, from_path, to_path)` move records.
- If both lists are empty, return `None`.
- Validate duplicate source paths and duplicate destination paths before
  touching disk.
- Validate every destination is either absent or is also one of the source paths
  in this same move set. If a destination exists outside the move set, raise
  `FileExistsError`.
- Stage every source to a deterministic temporary sibling path before moving any
  temp to its final destination. Use names that are easy to inspect, for
  example:

```python
tmp = src.with_name(f".{src.name}.chaos-{entry.event_id}-{index}.tmp")
```

- Then move temps to final destinations, creating parent directories.
- Return one `FilesystemAction` for the journal entry with:
  - `event_id=entry.event_id`
  - `action=TimelineActionName(entry.action)`
  - `target_asset_id` set to the first normalized move's `asset_id`
  - `from_path` and `to_path` set to the first normalized move's paths
  - `temp_path=None`

Keep exception wrapping in `apply_filesystem_action()` unchanged so any
collision or missing source routes through `FilesystemActionError`.

- [ ] **Step 6: Verify and commit**

```bash
uv run pytest tests/materializer/test_actions.py tests/materializer/test_preflight.py tests/materializer/test_hierarchy_moves.py tests/materializer/test_filesystem.py -q --no-cov
uv run ruff check src/chaos_librarian/materializer/actions.py src/chaos_librarian/materializer/phase_b/filesystem.py tests/materializer/test_actions.py tests/materializer/test_preflight.py tests/materializer/test_hierarchy_moves.py
uv run ruff format --check src/chaos_librarian/materializer/actions.py src/chaos_librarian/materializer/phase_b/filesystem.py tests/materializer/test_actions.py tests/materializer/test_preflight.py tests/materializer/test_hierarchy_moves.py
git add src/chaos_librarian/materializer/actions.py src/chaos_librarian/materializer/phase_b/filesystem.py tests/materializer/test_actions.py tests/materializer/test_preflight.py tests/materializer/test_hierarchy_moves.py
git commit -m "feat: materialize hierarchy path moves"
```

## Task 4: Materializer Failure and Fixture Conversion

**Files:**
- Modify: `tests/materializer/test_run.py`
- Modify: `tests/materializer/test_run_sprint7.py`
- Modify: `tests/fixtures/scenarios/voom-ci/*.yaml`

- [ ] **Step 1: Strengthen phase-B failure assertion**

In `tests/materializer/test_run.py`,
`test_materialize_phase_b_oserror_aborts_and_cleans_up`, add assertions after
loading the materialization report:

```python
    assert report.outcome is Outcome.FS_FAILED
    assert report.outcome is not Outcome.SUCCESS
    sentinel_payload = json.loads((out / ".chaos-librarian-run").read_text())
    assert sentinel_payload["state"] == "complete"
```

This keeps the existing failure-path contract explicit: no success outcome is
written after a filesystem failure, while cleanup still leaves a readable
completed failure run.

- [ ] **Step 2: Convert inline add-file scenario in `test_run.py`**

Replace the inline `schema_version: 11` / `works:` YAML in
`test_materialize_delete_then_add_file_restores_bytes_and_run_id` with:

```yaml
schema_version: 12
scenario_id: add-file-rejected
seed: 11
duration_scale: short
library:
  roots:
    - id: movies_hd
      path: movies-hd
movies:
  - id: movie_quasar
    title: Synthetic Quasar
    layout: movie_flat
    variants:
      - id: variant_hd
        label: hd
        bundle:
          id: bundle_hd
          assets:
            - id: asset_main
              role: primary_video
              container: mkv
              duration_seconds: 5
              video:
                source: color_bars
                codec: h264
                resolution: 1080p
              audio:
                - codec: aac
                  channels: stereo
                  language: eng
series: []
artists: []
timeline:
  - id: delete_001
    at: 1s
    action: delete_file
    target: asset_main
  - id: add_001
    at: 2s
    action: add_file
    target: asset_main
    to: movies-hd/new.mkv
```

Update the deleted initial-path assertion in that test. The rendered initial
movie path is:

```python
library / "movies-hd" / "Synthetic Quasar - hd.mkv"
```

- [ ] **Step 3: Convert `_STATIC_SCENARIO` in `test_run.py`**

Replace `_STATIC_SCENARIO` with a schema v12 movie scenario:

```yaml
schema_version: 12
scenario_id: static-test
seed: 1
duration_scale: short
library:
  roots:
    - id: r0
      path: library
movies:
  - id: movie_static
    title: Static
    layout: movie_flat
    variants:
      - id: va0
        label: hd
        bundle:
          id: b0
          assets:
            - id: a0
              role: main
              container: mkv
              duration_seconds: 1.0
              video:
                source: color_bars
                codec: h264
                resolution: hd
              audio:
                - source: sine
                  codec: aac
                  channels: stereo
                  language: eng
              subtitles:
                - codec: srt
                  language: eng
                  mode: sidecar
                  source: generated_srt
series: []
artists: []
timeline: []
```

Keep `_STATIC_SCENARIO_OPUS`, `_STATIC_SCENARIO_WITH_EMBEDDED_SUBS`, and
`_STATIC_SCENARIO_WITH_ASS_SUBS` as string replacements of the new v12 body.

- [ ] **Step 4: Convert `_REENCODE_SCENARIO_BODY` in `test_run_sprint7.py`**

Replace the `works:` tree with this `movies:` tree and add `series: []`,
`artists: []` before `timeline:`:

```yaml
movies:
  - id: movie_0
    title: T
    layout: movie_flat
    variants:
      - id: v0
        label: hd
        bundle:
          id: b0
          assets:
            - id: a0
              role: primary_video
              container: mkv
              duration_seconds: 1
              video:
                source: color_bars
                codec: h264
                resolution: hd
              audio:
                - codec: aac
                  channels: stereo
                  language: eng
series: []
artists: []
```

Set `schema_version: 12`.

- [ ] **Step 5: Convert voom-ci fixtures**

For each file under `tests/fixtures/scenarios/voom-ci/*.yaml`:

- set `schema_version: 12`;
- replace top-level `works:` with `movies:`;
- for each previous work row, keep the title, change its id from `work_*` to
  `movie_*`, add `layout: movie_flat`, and keep the `variants:` subtree
  unchanged;
- add top-level `series: []` and `artists: []` before `timeline:`.

Do not change scenario ids, asset ids, variant ids, bundle ids, timeline event
ids, codecs, or durations.

- [ ] **Step 6: Verify and commit**

```bash
uv run pytest tests/materializer/test_run.py tests/materializer/test_run_sprint7.py tests/contract/test_voom_ci_pack.py -q --no-cov
uv run pytest tests/integration/test_voom_ci_pack_real.py -q --no-cov
rg -n "works:|schema_version: 11" tests/materializer tests/fixtures/scenarios/voom-ci
uv run ruff check tests/materializer/test_run.py tests/materializer/test_run_sprint7.py tests/fixtures/scenarios/voom-ci tests/contract/test_voom_ci_pack.py
uv run ruff format --check tests/materializer/test_run.py tests/materializer/test_run_sprint7.py tests/fixtures/scenarios/voom-ci tests/contract/test_voom_ci_pack.py
git add tests/materializer/test_run.py tests/materializer/test_run_sprint7.py tests/fixtures/scenarios/voom-ci
git commit -m "test: convert materializer fixtures to hierarchies"
```

If the integration test skips because tools are unavailable, report the skip
explicitly. The `rg` command should produce no matches; if it finds inert
writer-test strings, convert them to v12 in the same commit.

## Task 5: Materializer Verification

**Files:**
- No source edits expected.

- [ ] **Step 1: Run focused materializer tests**

```bash
uv run pytest tests/materializer/test_audio_only.py tests/materializer/test_actions.py tests/materializer/test_preflight.py tests/materializer/test_ffmpeg_builder.py tests/materializer/test_synthesis.py tests/materializer/test_filesystem.py tests/materializer/test_hierarchy_moves.py tests/materializer/test_run.py tests/materializer/test_run_sprint7.py -q --no-cov
```

Expected: all selected tests pass.

- [ ] **Step 2: Run materializer-owned legacy scan**

```bash
rg -n "works:|schema_version: 11|Scenario\\.works|work_id|ManifestWork|WorkReport|work-report|reports/works" src/chaos_librarian/materializer tests/materializer tests/fixtures/scenarios/voom-ci
```

Expected: no matches. If intentional negative assertions are added later, filter
only those exact lines and record them in the final report.

- [ ] **Step 3: Run parent-plan gates**

```bash
uv run ruff check .
uv run ruff format --check .
uv run ty check src tests
uv run python -m chaos_librarian.schema_export --check
```

Expected: all commands pass with no warnings or schema drift.
