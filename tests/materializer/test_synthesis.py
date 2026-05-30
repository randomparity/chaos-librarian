"""Phase-A synthesis helper coverage."""

from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path

import pytest

from chaos_librarian.contract.capabilities import Capabilities, ReadyFor, ToolStatus
from chaos_librarian.contract.content_sources import (
    CacheDisposition,
    ContentSourceCapabilities,
    ContentSourceEvidence,
    ContentTrackKind,
)
from chaos_librarian.contract.manifest import ProbedMedia, ProbedStream, StreamKind
from chaos_librarian.contract.materialization import MaterializedAsset, ToolInvocation
from chaos_librarian.contract.scenario import (
    Asset,
    AudioChannelLayout,
    AudioSource,
    AudioTrack,
    EmbeddedChapters,
    EmbeddedCoverArt,
    MatroskaMuxingProfile,
    Mp4MoovPlacement,
    SubtitleCodec,
    SubtitleEncoding,
    SubtitleMode,
    SubtitleSource,
    SubtitleTimingProfile,
    SubtitleTrack,
    VideoResolutionSequence,
    VideoSource,
    VideoTrack,
)
from chaos_librarian.engine import run_plan
from chaos_librarian.engine.plan import PlanArtifacts
from chaos_librarian.materializer import synthesis as synthesis_mod
from chaos_librarian.materializer.errors import (
    SymlinkTargetMissingError,
    UnsupportedMaterializationError,
)
from chaos_librarian.materializer.synthesis import (
    MaterializeAssetResult,
    PhaseAResult,
    materialize_assets_phase_a,
    materialize_one_asset,
)
from chaos_librarian.materializer.tooling.recipes import FFmpegInput
from chaos_librarian.validation import prepare_run_input_from_bytes, run_validation

_RECIPE_DIGEST = "sha256:" + "f" * 64


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def test_materialize_assets_phase_a_collects_and_stamps_manifest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run_input = prepare_run_input_from_bytes(
        raw_bytes=b"""\
schema_version: 30
scenario_id: static-library
seed: 1
duration_scale: short
library:
  roots:
    - id: root_main
      path: library
movies:
  - id: w_movie
    title: Static Library Smoke Test
    layout: movie_flat
    variants:
      - id: va_hd
        label: hd
        bundle:
          id: b_hd
          assets:
            - id: a_hd_main
              role: main
              container: mkv
              duration_seconds: 2.0
              video:
                source: color_bars
                codec: h264
                resolution: hd
              audio:
                - source: sine
                  codec: aac
                  channels: stereo
                  language: eng
      - id: va_1080
        label: 1080p
        bundle:
          id: b_1080
          assets:
            - id: a_1080_main
              role: main
              container: mp4
              duration_seconds: 2.0
              video:
                source: solid_color
                codec: h264
                resolution: "1080p"
              audio:
                - source: channel_tones
                  codec: aac
                  channels: "5.1"
                  language: eng
      - id: va_sd_subs
        label: sd-subs
        bundle:
          id: b_sd_subs
          assets:
            - id: a_sd_main
              role: main
              container: mkv
              duration_seconds: 2.0
              video:
                source: mandelbrot
                codec: h264
                resolution: sd
              audio:
                - source: sine
                  codec: aac
                  channels: mono
                  language: eng
              subtitles:
                - source: generated_srt
                  codec: srt
                  language: eng
                  mode: sidecar
series: []
artists: []
timeline: []
""",
        source_label="test:static-library.yaml",
    )
    validation_report = run_validation(run_input)
    assert validation_report.ok
    artifacts = run_plan(run_input=run_input, validation_report=validation_report)

    monkeypatch.setattr(synthesis_mod, "materialize_one_asset", _fake_materialize_one_asset)

    phase_a = materialize_assets_phase_a(
        scenario=run_input.scenario,
        out_dir=tmp_path,
        artifacts=artifacts,
        caps=_caps(),
        stamp_manifest=True,
    )

    expected_assets = ["a_hd_main", "a_1080_main", "a_sd_main"]
    expected_paths = [
        "library/library/Static Library Smoke Test - hd.mkv",
        "library/library/Static Library Smoke Test - 1080p.mp4",
        "library/library/Static Library Smoke Test - sd-subs.mkv",
    ]
    assert [item.asset_id for item in phase_a.materialized_assets] == expected_assets
    assert [item.location_path for item in phase_a.materialized_assets] == expected_paths
    assert [item.asset_id for item in phase_a.content_sources] == expected_assets
    assert [item.command[-1] for item in phase_a.invocations] == expected_paths
    assert set(phase_a.probed_by_asset) == set(expected_assets)
    assert artifacts.current_manifest.sidecars
    assert all(version.content_hash is not None for version in artifacts.current_manifest.versions)
    assert all(sidecar.content_hash is not None for sidecar in artifacts.current_manifest.sidecars)


def test_materialize_assets_phase_a_passes_rendered_path_for_unsafe_asset_id(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run_input = prepare_run_input_from_bytes(
        raw_bytes=b"""\
schema_version: 30
scenario_id: unsafe-id-materialize
seed: 1
duration_scale: short
library:
  roots:
    - id: r
      path: r
movies:
  - id: movie_safe
    title: Rendered Safe
    layout: movie_flat
    variants:
      - id: variant_safe
        label: hd
        bundle:
          id: bundle_safe
          assets:
            - id: ../../../escape
              role: main
              container: mkv
              duration_seconds: 1
              video:
                source: color_bars
                codec: h264
                resolution: sd
              audio:
                - source: sine
                  codec: aac
                  channels: stereo
                  language: eng
series: []
artists: []
timeline: []
""",
        source_label="test:unsafe-id-materialize.yaml",
    )
    validation_report = run_validation(run_input)
    assert validation_report.ok
    artifacts = run_plan(run_input=run_input, validation_report=validation_report)
    monkeypatch.setattr(synthesis_mod, "materialize_one_asset", _fake_materialize_one_asset)

    phase_a = materialize_assets_phase_a(
        scenario=run_input.scenario,
        out_dir=tmp_path,
        artifacts=artifacts,
        caps=_caps(),
        stamp_manifest=True,
    )

    assert [item.location_path for item in phase_a.materialized_assets] == [
        "library/r/Rendered Safe - hd.mkv"
    ]
    assert [item.command[-1] for item in phase_a.invocations] == [
        "library/r/Rendered Safe - hd.mkv"
    ]


def test_materialize_one_asset_writes_declared_sidecar_next_to_rendered_media(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    asset = _asset_with_declared_sidecar("../../../escape")
    output_path = tmp_path / "run" / "library" / "r" / "Rendered Safe - hd.mkv"

    def fake_run_ffmpeg(argv: list[str], *, ffmpeg_version: str, timeout_s: float = 60.0):
        del timeout_s
        Path(argv[-1]).write_bytes(b"media")
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
            container="matroska,webm",
            duration_seconds=1,
            size_bytes=output_path.stat().st_size,
            streams=[ProbedStream(kind=StreamKind.VIDEO, codec="h264", width=640, height=480)],
        ),
    )

    result = materialize_one_asset(
        asset,
        1,
        tmp_path / "run",
        _caps(),
        0,
        rendered_relative_path="r/Rendered Safe - hd.mkv",
    )

    assert result.materialized_asset.location_path == "library/r/Rendered Safe - hd.mkv"
    assert (tmp_path / "run" / "library" / "r" / "Rendered Safe - hd.eng.srt").exists()
    assert not (tmp_path / "run" / "escape.eng.srt").exists()
    assert result.sidecar_hashes.keys() == {("../../../escape", "eng")}


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
            SubtitleTrack(
                codec=SubtitleCodec.SRT,
                language="eng",
                mode=SubtitleMode.SIDECAR,
                encoding=SubtitleEncoding.UTF8_BOM,
            ),
            SubtitleTrack(
                codec=SubtitleCodec.SRT,
                language="spa",
                mode=SubtitleMode.SIDECAR,
                encoding=SubtitleEncoding.UTF16_LE,
                timing_profile=SubtitleTimingProfile.OUT_OF_RANGE,
            ),
            SubtitleTrack(
                codec=SubtitleCodec.ASS,
                source=SubtitleSource.STYLED_ASS,
                language="jpn",
                mode=SubtitleMode.SIDECAR,
                timing_profile=SubtitleTimingProfile.OVERLAP,
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
    utf16_path = tmp_path / "run" / "library" / "r" / "Movie.spa.srt"
    ass_path = tmp_path / "run" / "library" / "r" / "Movie.jpn.ass"
    assert srt_path.read_bytes().startswith(b"\xef\xbb\xbf")
    assert utf16_path.read_bytes().startswith(b"\xff\xfe")
    assert b"[V4+ Styles]" in ass_path.read_bytes()
    assert result.sidecar_hashes[(asset.id, "eng")] == _sha256(srt_path.read_bytes())
    assert result.sidecar_hashes[(asset.id, "spa")] == _sha256(utf16_path.read_bytes())
    assert result.sidecar_hashes[(asset.id, "jpn")] == _sha256(ass_path.read_bytes())


def test_materialize_one_asset_writes_audio_only_track(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    asset = _track_audio_asset()
    output_path = tmp_path / "run" / "library" / "r" / "Artist" / "Album" / "01 - Song.flac"

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
            streams=[ProbedStream(kind=StreamKind.AUDIO, codec="flac")],
        ),
    )

    result = materialize_one_asset(
        asset,
        1,
        tmp_path / "run",
        _caps(),
        0,
        rendered_relative_path="r/Artist/Album/01 - Song.flac",
    )

    assert output_path.exists()
    assert result.materialized_asset.location_path == "library/r/Artist/Album/01 - Song.flac"
    assert [source.track_kind for source in result.content_sources] == [ContentTrackKind.AUDIO]
    assert result.sidecar_hashes == {}


def test_materialize_one_asset_records_mp4_moov_placement(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    asset = Asset(
        id="asset_mp4",
        role="main",
        container="mp4",
        duration_seconds=1.0,
        mp4_moov_placement=Mp4MoovPlacement.MOOV_AT_START,
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
    output_path = tmp_path / "run" / "library" / "r" / "Moov.mp4"
    captured: dict[str, Mp4MoovPlacement | None] = {}

    def fake_build_command(
        *,
        video: VideoTrack | None,
        video_input: object | None,
        audios: object,
        audio_inputs: object,
        output_path: Path,
        mp4_moov_placement: Mp4MoovPlacement | None,
        chapters_input: object | None = None,
        cover_art_input: object | None = None,
    ) -> list[str]:
        del video, video_input, audios, audio_inputs, chapters_input, cover_art_input
        captured["mp4_moov_placement"] = mp4_moov_placement
        return ["ffmpeg", "-i", "synthetic", str(output_path)]

    def fake_run_ffmpeg(argv: list[str], *, ffmpeg_version: str, timeout_s: float = 60.0):
        del ffmpeg_version, timeout_s
        Path(argv[-1]).write_bytes(b"media")
        return (
            ToolInvocation(
                tool="ffmpeg",
                version="7.1.1",
                command=argv,
                exit_code=0,
                duration_ns=1,
            ),
            "",
        )

    monkeypatch.setattr(synthesis_mod, "build_command", fake_build_command)
    monkeypatch.setattr(synthesis_mod, "run_ffmpeg", fake_run_ffmpeg)
    monkeypatch.setattr(
        synthesis_mod,
        "probe_file",
        lambda _path: ProbedMedia(
            container="mov,mp4,m4a,3gp,3g2,mj2",
            duration_seconds=1,
            size_bytes=output_path.stat().st_size,
            streams=[ProbedStream(kind=StreamKind.VIDEO, codec="h264", width=640, height=480)],
        ),
    )

    result = materialize_one_asset(
        asset,
        1,
        tmp_path / "run",
        _caps(),
        0,
        rendered_relative_path="r/Moov.mp4",
    )

    assert captured["mp4_moov_placement"] is Mp4MoovPlacement.MOOV_AT_START
    assert result.materialized_asset.mp4_moov_placement is Mp4MoovPlacement.MOOV_AT_START


def test_materialize_one_asset_threads_embedded_metadata_inputs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
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
    output_path = tmp_path / "run" / "library" / "r" / "Embedded.mp4"
    captured: dict[str, str] = {}

    def fake_build_command(
        *,
        video: VideoTrack | None,
        video_input: object | None,
        audios: object,
        audio_inputs: object,
        output_path: Path,
        mp4_moov_placement: Mp4MoovPlacement | None,
        chapters_input: FFmpegInput | None,
        cover_art_input: FFmpegInput | None,
    ) -> list[str]:
        del video, video_input, audios, audio_inputs, mp4_moov_placement
        assert chapters_input is not None
        assert chapters_input.file_path is not None
        assert cover_art_input is not None
        assert cover_art_input.file_path is not None
        captured["chapters"] = chapters_input.file_path.read_text(encoding="utf-8")
        captured["cover_name"] = cover_art_input.file_path.name
        return ["ffmpeg", "-i", "synthetic", str(output_path)]

    def fake_run_ffmpeg(argv: list[str], *, ffmpeg_version: str, timeout_s: float = 60.0):
        del timeout_s
        Path(argv[-1]).write_bytes(b"media")
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

    monkeypatch.setattr(synthesis_mod, "build_command", fake_build_command)
    monkeypatch.setattr(synthesis_mod, "run_ffmpeg", fake_run_ffmpeg)
    monkeypatch.setattr(
        synthesis_mod,
        "probe_file",
        lambda _path: ProbedMedia(
            container="mov,mp4,m4a,3gp,3g2,mj2",
            duration_seconds=1,
            size_bytes=output_path.stat().st_size,
            streams=[ProbedStream(kind=StreamKind.VIDEO, codec="h264", width=640, height=480)],
        ),
    )

    result = materialize_one_asset(
        asset,
        137,
        tmp_path / "run",
        _caps(),
        0,
        rendered_relative_path="r/Embedded.mp4",
    )

    assert len(result.prelude_invocations) == 1
    assert Path(result.prelude_invocations[0].command[-1]).name == captured["cover_name"]
    assert "[CHAPTER]" in captured["chapters"]
    assert "title=Scene 01 " in captured["chapters"]
    assert {source.track_kind for source in result.content_sources} == {
        ContentTrackKind.VIDEO,
        ContentTrackKind.AUDIO,
        ContentTrackKind.CHAPTERS,
        ContentTrackKind.COVER_ART,
    }


def test_materialize_one_asset_uses_mkvmerge_final_invocation_for_profile(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    asset = Asset(
        id="asset_muxed",
        role="main",
        container="mkv",
        duration_seconds=1.0,
        matroska_muxing_profile=MatroskaMuxingProfile.SHORT_CLUSTERS,
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
    final_path = tmp_path / "run" / "library" / "r" / "A.mkv"
    calls: list[list[str]] = []

    def fake_run_ffmpeg(argv: list[str], *, ffmpeg_version: str, timeout_s: float = 60.0):
        del timeout_s
        calls.append(argv)
        output = Path(argv[-1])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"temp media")
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

    def fake_run_mkvmerge(argv: list[str], *, mkvmerge_version: str, timeout_s: float = 60.0):
        del timeout_s
        calls.append(argv)
        output = Path(argv[argv.index("-o") + 1])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"final media")
        return (
            ToolInvocation(
                tool="mkvmerge",
                version=mkvmerge_version,
                command=argv,
                exit_code=0,
                duration_ns=1,
            ),
            "",
        )

    monkeypatch.setattr(synthesis_mod, "run_ffmpeg", fake_run_ffmpeg)
    monkeypatch.setattr(synthesis_mod, "run_mkvmerge", fake_run_mkvmerge)
    monkeypatch.setattr(
        synthesis_mod,
        "probe_file",
        lambda path: ProbedMedia(
            container="matroska,webm",
            duration_seconds=1.0,
            size_bytes=path.stat().st_size,
            streams=[ProbedStream(kind=StreamKind.VIDEO, codec="h264", width=640, height=480)],
        ),
    )

    result = materialize_one_asset(
        asset,
        138,
        tmp_path / "run",
        _caps(mkvtoolnix=True),
        0,
        rendered_relative_path="r/A.mkv",
    )

    assert result.invocation.tool == "mkvmerge"
    assert result.prelude_invocations[0].tool == "ffmpeg"
    assert calls[0][-1] != str(final_path)
    assert calls[1][calls[1].index("-o") + 1] == str(final_path)
    assert any(source.track_kind is ContentTrackKind.MUXING for source in result.content_sources)


def test_materialize_one_asset_rejects_audio_only_sidecar_before_writing(
    tmp_path: Path,
) -> None:
    asset = Asset(
        id="track_asset",
        role="main",
        container="flac",
        duration_seconds=1,
        audio=(
            AudioTrack(
                source=AudioSource.SINE,
                codec="flac",
                channels=AudioChannelLayout.STEREO,
                language="eng",
            ),
        ),
        subtitles=(
            SubtitleTrack(
                codec=SubtitleCodec.SRT,
                language="eng",
                mode=SubtitleMode.SIDECAR,
            ),
        ),
    )

    with pytest.raises(UnsupportedMaterializationError) as exc_info:
        materialize_one_asset(
            asset,
            1,
            tmp_path / "run",
            _caps(),
            0,
            rendered_relative_path="r/Artist/Album/01 - Song.flac",
        )

    assert exc_info.value.field == "subtitles"
    sidecar_path = tmp_path / "run" / "library" / "r" / "Artist" / "Album" / "01 - Song.eng.srt"
    assert not sidecar_path.exists()


def test_materialize_one_asset_writes_resolution_switch_video(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    asset = _resolution_switch_asset()
    output_path = tmp_path / "run" / "library" / "r" / "Resolution Switch - sd-to-hd.ts"
    _patch_successful_ffmpeg(monkeypatch, output_path)

    result = materialize_one_asset(
        asset,
        133,
        tmp_path / "run",
        _caps(),
        2,
        rendered_relative_path="r/Resolution Switch - sd-to-hd.ts",
    )

    assert len(result.prelude_invocations) == 2
    assert result.invocation.command[result.invocation.command.index("-c") + 1] == "copy"
    assert result.materialized_asset.invocation_index == 2
    # Both the SD and HD segments are encoded and concatenated, so both
    # resolved sources must appear in the replay evidence with distinct recipes.
    assert len(result.content_sources) == 2
    assert [source.track_kind for source in result.content_sources] == [
        ContentTrackKind.VIDEO,
        ContentTrackKind.VIDEO,
    ]
    assert all(
        source.resolution_sequence is VideoResolutionSequence.SD_TO_HD
        for source in result.content_sources
    )
    sd_evidence, hd_evidence = result.content_sources
    assert sd_evidence.recipe_digest != hd_evidence.recipe_digest
    assert output_path.exists()


def test_materialize_one_asset_rejects_resolution_switch_audio_before_writing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    audio = AudioTrack(
        source=AudioSource.SINE,
        codec="aac",
        channels=AudioChannelLayout.STEREO,
        language="eng",
    )
    asset = _resolution_switch_asset().model_copy(update={"audio": (audio,)})
    output_path = tmp_path / "run" / "library" / "r" / "Resolution Switch - sd-to-hd.ts"
    _patch_successful_ffmpeg(monkeypatch, output_path)

    with pytest.raises(UnsupportedMaterializationError) as exc:
        materialize_one_asset(
            asset,
            133,
            tmp_path / "run",
            _caps(),
            0,
            rendered_relative_path="r/Resolution Switch - sd-to-hd.ts",
        )

    assert exc.value.field == "audio"
    assert not output_path.exists()


def test_phase_a_appends_resolution_switch_invocations_in_order(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run_input = prepare_run_input_from_bytes(
        raw_bytes=b"""\
schema_version: 30
scenario_id: resolution-switch-phase-a
seed: 133
duration_scale: short
library:
  roots:
    - id: r
      path: r
movies:
  - id: movie_switch
    title: Resolution Switch
    layout: movie_flat
    variants:
      - id: variant_switch
        label: sd-to-hd
        bundle:
          id: bundle_switch
          assets:
            - id: asset_switch
              role: main
              container: ts
              duration_seconds: 1.0
              video:
                source: color_bars
                codec: h264
                resolution: sd
                resolution_sequence: sd_to_hd
series: []
artists: []
timeline: []
""",
        source_label="test:resolution-switch-phase-a.yaml",
    )
    validation_report = run_validation(run_input)
    assert validation_report.ok
    artifacts = run_plan(run_input=run_input, validation_report=validation_report)
    _patch_successful_ffmpeg(
        monkeypatch,
        tmp_path / "run" / "library" / "r" / "Resolution Switch - sd-to-hd.ts",
    )

    phase_a = materialize_assets_phase_a(
        scenario=run_input.scenario,
        out_dir=tmp_path / "run",
        artifacts=artifacts,
        caps=_caps(),
        stamp_manifest=True,
    )

    assert len(phase_a.invocations) == 3
    assert phase_a.invocations[0].command[-1].endswith("segment-sd.ts")
    assert phase_a.invocations[1].command[-1].endswith("segment-hd.ts")
    assert phase_a.invocations[2].command[phase_a.invocations[2].command.index("-c") + 1] == "copy"
    assert phase_a.materialized_assets[0].invocation_index == 2


def _asset_with_declared_sidecar(asset_id: str):
    scenario = prepare_run_input_from_bytes(
        raw_bytes=f"""\
schema_version: 30
scenario_id: sidecar-materialize
seed: 1
duration_scale: short
library:
  roots:
    - id: r
      path: r
movies:
  - id: movie_safe
    title: Rendered Safe
    layout: movie_flat
    variants:
      - id: variant_safe
        label: hd
        bundle:
          id: bundle_safe
          assets:
            - id: {asset_id}
              role: main
              container: mkv
              duration_seconds: 1
              video:
                source: color_bars
                codec: h264
                resolution: sd
              audio:
                - source: sine
                  codec: aac
                  channels: stereo
                  language: eng
              subtitles:
                - source: generated_srt
                  codec: srt
                  language: eng
                  mode: sidecar
series: []
artists: []
timeline: []
""".encode(),
        source_label="test:sidecar-materialize.yaml",
    ).scenario
    return scenario.movies[0].variants[0].bundle.assets[0]


def _track_audio_asset():
    scenario = prepare_run_input_from_bytes(
        raw_bytes=b"""\
schema_version: 30
scenario_id: audio-track-materialize
seed: 1
duration_scale: short
library:
  roots:
    - id: r
      path: r
movies: []
series: []
artists:
  - id: artist_safe
    name: Artist
    layout: artist_album_flat
    track_naming: track_number_title
    albums:
      - id: album_safe
        title: Album
        discs:
          - id: disc_safe
            disc_number: 1
            tracks:
              - id: track_safe
                track_number: 1
                title: Song
                variants:
                  - id: variant_safe
                    label: flac
                    bundle:
                      id: bundle_safe
                      assets:
                        - id: track_asset
                          role: main
                          container: flac
                          duration_seconds: 1
                          audio:
                            - source: sine
                              codec: flac
                              channels: stereo
                              language: eng
timeline: []
""",
        source_label="test:audio-track-materialize.yaml",
    ).scenario
    return scenario.artists[0].albums[0].discs[0].tracks[0].variants[0].bundle.assets[0]


def _resolution_switch_asset() -> Asset:
    return Asset(
        id="asset_switch",
        role="main",
        container="ts",
        duration_seconds=1.0,
        video=VideoTrack(
            source=VideoSource.COLOR_BARS,
            codec="h264",
            resolution="sd",
            resolution_sequence=VideoResolutionSequence.SD_TO_HD,
        ),
    )


def _patch_successful_ffmpeg(monkeypatch: pytest.MonkeyPatch, final_path: Path) -> None:
    def fake_run_ffmpeg(argv: list[str], *, ffmpeg_version: str, timeout_s: float = 60.0):
        del timeout_s
        output = Path(argv[-1])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"media")
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
            container="mpegts",
            duration_seconds=1.0,
            size_bytes=final_path.stat().st_size,
            streams=[ProbedStream(kind=StreamKind.VIDEO, codec="h264", width=1280, height=720)],
        ),
    )


def _caps(*, mkvtoolnix: bool = False) -> Capabilities:
    return Capabilities(
        schema_version=7,
        ffmpeg=ToolStatus(found=True, version="7.1.1", path="/x/ffmpeg", meets_minimum=True),
        ffprobe=ToolStatus(found=True, version="7.1.1", path="/x/ffprobe", meets_minimum=True),
        mkvtoolnix=ToolStatus(
            found=mkvtoolnix,
            version="98.0" if mkvtoolnix else None,
            path="/x/mkvmerge" if mkvtoolnix else None,
            meets_minimum=mkvtoolnix,
        ),
        platform="test",
        content_sources=ContentSourceCapabilities(),
        ready_for=ReadyFor(
            materialize_static=True,
            materialize_filesystem_mutations=True,
            materialize_media_mutations=False,
            materialize_hevc_video=True,
            materialize_hdr_video=True,
            materialize_resolution_switch_video=True,
            materialize_audio_recipes=True,
            materialize_matroska_muxing_profiles=True,
            materialize_webm_video=True,
        ),
    )


def _fake_materialize_one_asset(
    asset,
    resolved_seed,
    out_dir: Path,
    caps,
    invocation_index: int,
    *,
    rendered_relative_path: str,
    skip_languages=frozenset(),
) -> MaterializeAssetResult:
    del resolved_seed, out_dir, caps
    data = f"{asset.id}-bytes".encode()
    content_hash = "sha256:" + hashlib.sha256(data).hexdigest()
    sidecar_hashes = {
        (asset.id, sub.language): "sha256:" + hashlib.sha256(sub.language.encode()).hexdigest()
        for sub in asset.subtitles
        if sub.language not in skip_languages
    }
    return MaterializeAssetResult(
        invocation=ToolInvocation(
            tool="ffmpeg",
            version="7.1.1",
            command=["ffmpeg", str(Path("library") / rendered_relative_path)],
            exit_code=0,
            duration_ns=1,
        ),
        materialized_asset=MaterializedAsset(
            asset_id=asset.id,
            location_path=str(Path("library") / rendered_relative_path),
            content_hash=content_hash,
            size_bytes=len(data),
            duration_seconds=asset.duration_seconds,
            invocation_index=invocation_index,
        ),
        probed=ProbedMedia(
            container=asset.container,
            duration_seconds=asset.duration_seconds,
            size_bytes=len(data),
            streams=[ProbedStream(kind=StreamKind.VIDEO, codec="h264", width=640, height=480)],
        ),
        sidecar_hashes=sidecar_hashes,
        content_sources=(
            ContentSourceEvidence(
                asset_id=asset.id,
                track_kind=ContentTrackKind.VIDEO,
                source="fake-video",
                provider="fake-provider",
                recipe_digest=_RECIPE_DIGEST,
                cache_disposition=CacheDisposition.NOT_CACHEABLE,
            ),
        ),
    )


_SAME_CONTENT_SCENARIO = b"""\
schema_version: 30
scenario_id: same-content
seed: 1
duration_scale: short
library:
  roots:
    - id: root_main
      path: library
movies:
  - id: w_movie
    title: Dup
    layout: movie_flat
    variants:
      - id: va_a
        label: a
        bundle:
          id: b_a
          assets:
            - id: a_ref
              role: main
              container: mkv
              duration_seconds: 2.0
              video: {source: color_bars, codec: h264, resolution: hd}
              audio: [{source: sine, codec: aac, channels: stereo, language: eng}]
      - id: va_b
        label: b
        bundle:
          id: b_b
          assets:
            - id: a_dup
              role: main
              container: mkv
              duration_seconds: 2.0
              video: {source: color_bars, codec: h264, resolution: hd}
              audio: [{source: sine, codec: aac, channels: stereo, language: eng}]
              same_content_as: a_ref
series: []
artists: []
timeline: []
"""


def _file_writing_fake(
    asset,
    resolved_seed,
    out_dir: Path,
    caps,
    invocation_index: int,
    *,
    rendered_relative_path: str,
    skip_languages=frozenset(),
) -> MaterializeAssetResult:
    """Like ``_fake_materialize_one_asset`` but writes real bytes to disk.

    The copy short-circuit reads the referent file off disk and re-probes it,
    so the referent fake must materialize an actual file.
    """
    del resolved_seed, caps, skip_languages
    output = out_dir / "library" / rendered_relative_path
    output.parent.mkdir(parents=True, exist_ok=True)
    data = f"{asset.id}-bytes".encode()
    output.write_bytes(data)
    content_hash = "sha256:" + hashlib.sha256(data).hexdigest()
    return MaterializeAssetResult(
        invocation=ToolInvocation(
            tool="ffmpeg",
            version="7.1.1",
            command=["ffmpeg", str(output)],
            exit_code=0,
            duration_ns=1,
        ),
        materialized_asset=MaterializedAsset(
            asset_id=asset.id,
            location_path=str(output.relative_to(out_dir)),
            content_hash=content_hash,
            size_bytes=len(data),
            duration_seconds=asset.duration_seconds,
            invocation_index=invocation_index,
        ),
        probed=ProbedMedia(
            container=asset.container,
            duration_seconds=asset.duration_seconds,
            size_bytes=len(data),
            streams=[ProbedStream(kind=StreamKind.VIDEO, codec="h264", width=640, height=480)],
        ),
        sidecar_hashes={},
        content_sources=(
            ContentSourceEvidence(
                asset_id=asset.id,
                track_kind=ContentTrackKind.VIDEO,
                source="color_bars",
                provider="builtin-lavfi",
                recipe_digest="sha256:" + "c" * 64,
                cache_disposition=CacheDisposition.NOT_CACHEABLE,
            ),
        ),
        prelude_invocations=(),
    )


def _probe_real_file(path: Path) -> ProbedMedia:
    return ProbedMedia(
        container="matroska",
        duration_seconds=2.0,
        size_bytes=path.stat().st_size,
        streams=[ProbedStream(kind=StreamKind.VIDEO, codec="h264", width=640, height=480)],
    )


def test_same_content_as_copies_referent_bytes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run_input = prepare_run_input_from_bytes(
        raw_bytes=_SAME_CONTENT_SCENARIO, source_label="test:same-content.yaml"
    )
    assert run_validation(run_input).ok
    artifacts = run_plan(run_input=run_input, validation_report=run_validation(run_input))
    monkeypatch.setattr(synthesis_mod, "materialize_one_asset", _file_writing_fake)
    monkeypatch.setattr(synthesis_mod, "probe_file", _probe_real_file)

    phase_a = materialize_assets_phase_a(
        scenario=run_input.scenario,
        out_dir=tmp_path,
        artifacts=artifacts,
        caps=_caps(),
        stamp_manifest=True,
    )

    by_id = {m.asset_id: m for m in phase_a.materialized_assets}
    ref, dup = by_id["a_ref"], by_id["a_dup"]
    # byte-identical file → identical full content_hash
    ref_file = tmp_path / ref.location_path
    dup_file = tmp_path / dup.location_path
    assert dup_file.read_bytes() == ref_file.read_bytes()
    assert dup.content_hash == ref.content_hash
    # both manifest versions carry the same hash
    versions = {v.asset_id: v.content_hash for v in artifacts.current_manifest.versions}
    assert versions["a_dup"] == versions["a_ref"]
    # invocation_index resolves to a synthetic copy invocation
    copy_invocation = phase_a.invocations[dup.invocation_index]
    assert copy_invocation.tool == "same_content_copy"
    assert copy_invocation.exit_code == 0
    # the duplicate contributes no content-source evidence
    assert [e.asset_id for e in phase_a.content_sources] == ["a_ref"]
    # re-probed (size matches the copied file)
    assert dup.size_bytes == dup_file.stat().st_size


def _hardlink_scenario(extra_asset_yaml: bytes = b"") -> bytes:
    """A two-asset hardlink scenario; ``extra_asset_yaml`` appends a third asset."""
    return (
        b"""\
schema_version: 30
scenario_id: hardlink
seed: 1
duration_scale: short
library:
  roots:
    - id: root_main
      path: library
movies:
  - id: w_movie
    title: Link
    layout: movie_flat
    variants:
      - id: va_a
        label: a
        bundle:
          id: b_a
          assets:
            - id: a_ref
              role: main
              container: mkv
              duration_seconds: 2.0
              video: {source: color_bars, codec: h264, resolution: hd}
              audio: [{source: sine, codec: aac, channels: stereo, language: eng}]
      - id: va_b
        label: b
        bundle:
          id: b_b
          assets:
            - id: a_link
              role: main
              container: mkv
              duration_seconds: 2.0
              video: {source: color_bars, codec: h264, resolution: hd}
              audio: [{source: sine, codec: aac, channels: stereo, language: eng}]
              hardlinked_to: a_ref
"""
        + extra_asset_yaml
        + b"""\
series: []
artists: []
timeline: []
"""
    )


def _run_phase_a(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, scenario_bytes: bytes
) -> tuple[PhaseAResult, dict[str, MaterializedAsset], PlanArtifacts]:
    run_input = prepare_run_input_from_bytes(
        raw_bytes=scenario_bytes, source_label="test:hardlink.yaml"
    )
    assert run_validation(run_input).ok
    artifacts = run_plan(run_input=run_input, validation_report=run_validation(run_input))
    monkeypatch.setattr(synthesis_mod, "materialize_one_asset", _file_writing_fake)
    monkeypatch.setattr(synthesis_mod, "probe_file", _probe_real_file)
    phase_a = materialize_assets_phase_a(
        scenario=run_input.scenario,
        out_dir=tmp_path,
        artifacts=artifacts,
        caps=_caps(),
        stamp_manifest=True,
    )
    by_id = {m.asset_id: m for m in phase_a.materialized_assets}
    return phase_a, by_id, artifacts


def test_hardlinked_to_shares_one_inode(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    phase_a, by_id, artifacts = _run_phase_a(monkeypatch, tmp_path, _hardlink_scenario())
    ref, link = by_id["a_ref"], by_id["a_link"]
    ref_file = tmp_path / ref.location_path
    link_file = tmp_path / link.location_path
    ref_stat, link_stat = ref_file.stat(), link_file.stat()
    # one shared inode (the link-not-copy proof) and link count >= 2
    assert link_stat.st_ino == ref_stat.st_ino
    assert link_stat.st_dev == ref_stat.st_dev
    assert ref_stat.st_nlink >= 2
    assert link_stat.st_nlink >= 2
    # byte-identical content → identical full content_hash
    assert link_file.read_bytes() == ref_file.read_bytes()
    assert link.content_hash == ref.content_hash
    # both manifest versions carry the same hash
    versions = {v.asset_id: v.content_hash for v in artifacts.current_manifest.versions}
    assert versions["a_link"] == versions["a_ref"]
    # invocation_index resolves to a synthetic hardlink invocation
    link_invocation = phase_a.invocations[link.invocation_index]
    assert link_invocation.tool == "hardlink"
    assert link_invocation.exit_code == 0
    # the link contributes no content-source evidence
    assert [e.asset_id for e in phase_a.content_sources] == ["a_ref"]
    # re-probed (size matches the linked file)
    assert link.size_bytes == link_file.stat().st_size


def test_hardlinked_to_mutation_propagates(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _phase_a, by_id, _artifacts = _run_phase_a(monkeypatch, tmp_path, _hardlink_scenario())
    ref_file = tmp_path / by_id["a_ref"].location_path
    link_file = tmp_path / by_id["a_link"].location_path
    # writing through one path's inode is observed through the other (shared inode)
    ref_file.write_bytes(b"mutated-through-ref")
    assert link_file.read_bytes() == b"mutated-through-ref"


_HARDLINK_CHAIN_ASSET = b"""\
      - id: va_c
        label: c
        bundle:
          id: b_c
          assets:
            - id: a_link2
              role: main
              container: mkv
              duration_seconds: 2.0
              video: {source: color_bars, codec: h264, resolution: hd}
              audio: [{source: sine, codec: aac, channels: stereo, language: eng}]
              hardlinked_to: a_link
"""


def test_hardlinked_to_chain_shares_one_inode(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _phase_a, by_id, _artifacts = _run_phase_a(
        monkeypatch, tmp_path, _hardlink_scenario(_HARDLINK_CHAIN_ASSET)
    )
    inodes = {
        name: (tmp_path / by_id[name].location_path).stat().st_ino
        for name in ("a_ref", "a_link", "a_link2")
    }
    # C -> B -> A all resolve to one shared inode transitively
    assert len(set(inodes.values())) == 1
    assert (tmp_path / by_id["a_ref"].location_path).stat().st_nlink == 3


_HARDLINK_TO_DUPLICATE_SCENARIO = b"""\
schema_version: 30
scenario_id: hardlink-dup
seed: 1
duration_scale: short
library:
  roots:
    - id: root_main
      path: library
movies:
  - id: w_movie
    title: LinkDup
    layout: movie_flat
    variants:
      - id: va_a
        label: a
        bundle:
          id: b_a
          assets:
            - id: a_ref
              role: main
              container: mkv
              duration_seconds: 2.0
              video: {source: color_bars, codec: h264, resolution: hd}
              audio: [{source: sine, codec: aac, channels: stereo, language: eng}]
      - id: va_b
        label: b
        bundle:
          id: b_b
          assets:
            - id: a_dup
              role: main
              container: mkv
              duration_seconds: 2.0
              video: {source: color_bars, codec: h264, resolution: hd}
              audio: [{source: sine, codec: aac, channels: stereo, language: eng}]
              same_content_as: a_ref
      - id: va_c
        label: c
        bundle:
          id: b_c
          assets:
            - id: a_link_dup
              role: main
              container: mkv
              duration_seconds: 2.0
              video: {source: color_bars, codec: h264, resolution: hd}
              audio: [{source: sine, codec: aac, channels: stereo, language: eng}]
              hardlinked_to: a_dup
series: []
artists: []
timeline: []
"""


def test_hardlinked_to_a_same_content_duplicate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _phase_a, by_id, _artifacts = _run_phase_a(
        monkeypatch, tmp_path, _HARDLINK_TO_DUPLICATE_SCENARIO
    )
    dup_ino = (tmp_path / by_id["a_dup"].location_path).stat()
    link_ino = (tmp_path / by_id["a_link_dup"].location_path).stat()
    ref_ino = (tmp_path / by_id["a_ref"].location_path).stat()
    # the link shares the *duplicate's* inode, which is a copy (distinct from a_ref's)
    assert link_ino.st_ino == dup_ino.st_ino
    assert dup_ino.st_ino != ref_ino.st_ino
    assert dup_ino.st_nlink == 2


def test_hardlinked_to_unset_skips_os_link(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run_input = prepare_run_input_from_bytes(
        raw_bytes=_SAME_CONTENT_SCENARIO, source_label="test:no-link.yaml"
    )
    assert run_validation(run_input).ok
    artifacts = run_plan(run_input=run_input, validation_report=run_validation(run_input))
    monkeypatch.setattr(synthesis_mod, "materialize_one_asset", _file_writing_fake)
    monkeypatch.setattr(synthesis_mod, "probe_file", _probe_real_file)

    def _fail_link(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("os.link must not be called when no asset sets hardlinked_to")

    monkeypatch.setattr(synthesis_mod.os, "link", _fail_link)
    # _SAME_CONTENT_SCENARIO sets same_content_as but no hardlinked_to → no os.link.
    materialize_assets_phase_a(
        scenario=run_input.scenario,
        out_dir=tmp_path,
        artifacts=artifacts,
        caps=_caps(),
        stamp_manifest=True,
    )


def _symlink_in_root_scenario() -> bytes:
    return b"""\
schema_version: 30
scenario_id: symlink-in-root
seed: 1
duration_scale: short
library:
  roots:
    - id: root_main
      path: library
movies:
  - id: w_movie
    title: Link
    layout: movie_flat
    variants:
      - id: va_a
        label: a
        bundle:
          id: b_a
          assets:
            - id: a_ref
              role: main
              container: mkv
              duration_seconds: 2.0
              video: {source: color_bars, codec: h264, resolution: hd}
              audio: [{source: sine, codec: aac, channels: stereo, language: eng}]
      - id: va_b
        label: b
        bundle:
          id: b_b
          assets:
            - id: a_link
              role: main
              container: mkv
              duration_seconds: 2.0
              video: {source: color_bars, codec: h264, resolution: hd}
              audio: [{source: sine, codec: aac, channels: stereo, language: eng}]
              symlink: {to_asset: a_ref}
series: []
artists: []
timeline: []
"""


def _symlink_escaping_scenario() -> bytes:
    return b"""\
schema_version: 30
scenario_id: symlink-escaping
seed: 1
duration_scale: short
library:
  roots:
    - id: root_main
      path: library
movies:
  - id: w_movie
    title: Link
    layout: movie_flat
    variants:
      - id: va_a
        label: a
        bundle:
          id: b_a
          assets:
            - id: a_link
              role: main
              container: mkv
              duration_seconds: 2.0
              video: {source: color_bars, codec: h264, resolution: hd}
              audio: [{source: sine, codec: aac, channels: stereo, language: eng}]
              symlink: {to_run_dir_path: external-store/clip.mkv}
series: []
artists: []
timeline: []
"""


def test_symlink_to_asset_materializes_relative_symlink(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    phase_a, by_id, artifacts = _run_phase_a(monkeypatch, tmp_path, _symlink_in_root_scenario())
    ref, link = by_id["a_ref"], by_id["a_link"]
    ref_file = tmp_path / ref.location_path
    link_file = tmp_path / link.location_path
    # the referrer path is a real symlink
    assert link_file.is_symlink()
    # the stored target is relative (run-dir portable), not absolute
    target = os.readlink(link_file)
    assert not os.path.isabs(target)
    # following the link reaches the referent's bytes
    assert link_file.read_bytes() == ref_file.read_bytes()
    assert link.content_hash == ref.content_hash
    # invocation_index resolves to a synthetic symlink invocation
    link_invocation = phase_a.invocations[link.invocation_index]
    assert link_invocation.tool == "symlink"
    assert link_invocation.exit_code == 0
    # the link contributes no content-source evidence
    assert [e.asset_id for e in phase_a.content_sources] == ["a_ref"]
    # re-probed (size matches the resolved target)
    assert link.size_bytes == link_file.stat().st_size
    # manifest records the link's own location and the resolved-target hash
    versions = {v.asset_id: v.content_hash for v in artifacts.current_manifest.versions}
    assert versions["a_link"] == versions["a_ref"]


def test_symlink_to_asset_resolves_after_tree_relocation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    out_dir = tmp_path / "run-a"
    out_dir.mkdir()
    run_input = prepare_run_input_from_bytes(
        raw_bytes=_symlink_in_root_scenario(), source_label="test:symlink.yaml"
    )
    assert run_validation(run_input).ok
    artifacts = run_plan(run_input=run_input, validation_report=run_validation(run_input))
    monkeypatch.setattr(synthesis_mod, "materialize_one_asset", _file_writing_fake)
    monkeypatch.setattr(synthesis_mod, "probe_file", _probe_real_file)
    phase_a = materialize_assets_phase_a(
        scenario=run_input.scenario,
        out_dir=out_dir,
        artifacts=artifacts,
        caps=_caps(),
        stamp_manifest=True,
    )
    by_id = {m.asset_id: m for m in phase_a.materialized_assets}
    link_rel = by_id["a_link"].location_path
    ref_rel = by_id["a_ref"].location_path
    # relocate the whole run-dir tree to a new absolute path, preserving symlinks
    moved = tmp_path / "run-b"
    shutil.copytree(out_dir, moved, symlinks=True)
    moved_link = moved / link_rel
    assert moved_link.is_symlink()
    # the relative target still resolves to the referent's bytes after the move
    assert moved_link.read_bytes() == (moved / ref_rel).read_bytes()


def test_symlink_to_run_dir_path_materializes_escaping_link(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run_input = prepare_run_input_from_bytes(
        raw_bytes=_symlink_escaping_scenario(), source_label="test:symlink-escaping.yaml"
    )
    assert run_validation(run_input).ok
    artifacts = run_plan(run_input=run_input, validation_report=run_validation(run_input))
    monkeypatch.setattr(synthesis_mod, "materialize_one_asset", _file_writing_fake)
    monkeypatch.setattr(synthesis_mod, "probe_file", _probe_real_file)
    # create the out-of-library target under the tmp run dir (never a real system path)
    target = tmp_path / "external-store" / "clip.mkv"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"escaping-target-bytes")

    phase_a = materialize_assets_phase_a(
        scenario=run_input.scenario,
        out_dir=tmp_path,
        artifacts=artifacts,
        caps=_caps(),
        stamp_manifest=True,
    )
    by_id = {m.asset_id: m for m in phase_a.materialized_assets}
    link_file = tmp_path / by_id["a_link"].location_path
    assert link_file.is_symlink()
    # stored target is relative and resolves out of library/ to the created target
    assert not os.path.isabs(os.readlink(link_file))
    assert link_file.read_bytes() == b"escaping-target-bytes"
    # the asset path itself stays contained (under library/) — no escape on it
    assert link_file.resolve().is_relative_to(tmp_path)


def test_symlink_missing_target_fails_loud(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run_input = prepare_run_input_from_bytes(
        raw_bytes=_symlink_escaping_scenario(), source_label="test:symlink-missing.yaml"
    )
    assert run_validation(run_input).ok
    artifacts = run_plan(run_input=run_input, validation_report=run_validation(run_input))
    monkeypatch.setattr(synthesis_mod, "materialize_one_asset", _file_writing_fake)
    monkeypatch.setattr(synthesis_mod, "probe_file", _probe_real_file)
    # target file intentionally NOT created → fail loud, not silent / unhandled
    with pytest.raises(SymlinkTargetMissingError) as exc_info:
        materialize_assets_phase_a(
            scenario=run_input.scenario,
            out_dir=tmp_path,
            artifacts=artifacts,
            caps=_caps(),
            stamp_manifest=True,
        )
    assert exc_info.value.error_code == "E_MATERIALIZE_SYMLINK_TARGET_MISSING"


_SYMLINK_CHAIN_SCENARIO = b"""\
schema_version: 30
scenario_id: symlink-chain
seed: 1
duration_scale: short
library:
  roots:
    - id: root_main
      path: library
movies:
  - id: w_movie
    title: Chain
    layout: movie_flat
    variants:
      - id: va_a
        label: a
        bundle:
          id: b_a
          assets:
            - id: a_ref
              role: main
              container: mkv
              duration_seconds: 2.0
              video: {source: color_bars, codec: h264, resolution: hd}
              audio: [{source: sine, codec: aac, channels: stereo, language: eng}]
      - id: va_b
        label: b
        bundle:
          id: b_b
          assets:
            - id: a_link
              role: main
              container: mkv
              duration_seconds: 2.0
              video: {source: color_bars, codec: h264, resolution: hd}
              audio: [{source: sine, codec: aac, channels: stereo, language: eng}]
              symlink: {to_asset: a_ref}
      - id: va_c
        label: c
        bundle:
          id: b_c
          assets:
            - id: a_link2
              role: main
              container: mkv
              duration_seconds: 2.0
              video: {source: color_bars, codec: h264, resolution: hd}
              audio: [{source: sine, codec: aac, channels: stereo, language: eng}]
              symlink: {to_asset: a_link}
series: []
artists: []
timeline: []
"""


def test_symlink_chain_follows_transitively(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _phase_a, by_id, _artifacts = _run_phase_a(monkeypatch, tmp_path, _SYMLINK_CHAIN_SCENARIO)
    ref_file = tmp_path / by_id["a_ref"].location_path
    link2_file = tmp_path / by_id["a_link2"].location_path
    # a_link2 -> a_link -> a_ref: reading the chained link reaches a_ref's bytes
    assert link2_file.is_symlink()
    assert link2_file.read_bytes() == ref_file.read_bytes()


def test_symlink_unset_skips_os_symlink(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run_input = prepare_run_input_from_bytes(
        raw_bytes=_SAME_CONTENT_SCENARIO, source_label="test:no-symlink.yaml"
    )
    assert run_validation(run_input).ok
    artifacts = run_plan(run_input=run_input, validation_report=run_validation(run_input))
    monkeypatch.setattr(synthesis_mod, "materialize_one_asset", _file_writing_fake)
    monkeypatch.setattr(synthesis_mod, "probe_file", _probe_real_file)

    def _fail_symlink(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("os.symlink must not be called when no asset sets symlink")

    monkeypatch.setattr(synthesis_mod.os, "symlink", _fail_symlink)
    materialize_assets_phase_a(
        scenario=run_input.scenario,
        out_dir=tmp_path,
        artifacts=artifacts,
        caps=_caps(),
        stamp_manifest=True,
    )
