"""Per-rule tests for static media values materialize can synthesize."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from chaos_librarian.validation import codes, prepare_run_input, run_validation


@dataclass(frozen=True)
class ResolutionSwitchCase:
    name: str
    field_suffix: str
    container: str = "ts"
    video_source: str = "color_bars"
    video_codec: str = "h264"
    video_resolution: str = "sd"
    audio: bool = False
    subtitles: bool = False
    vfr_cadence: str | None = None
    field_order: str | None = None
    color_space: str | None = None
    color_range: str | None = None
    hdr_mode: str | None = None


def _write_track_scenario(
    path: Path,
    *,
    container: str,
    codec: str,
    source: str = "sine",
    noise_color: str | None = None,
    sample_rate: int = 48000,
    sample_format: str | None = None,
) -> None:
    noise_color_line = (
        f"                              noise_color: {noise_color}\n" if noise_color else ""
    )
    sample_format_line = (
        f"                              sample_format: {sample_format}\n" if sample_format else ""
    )
    path.write_text(
        f"""schema_version: 19
scenario_id: track-{container}-validation-smoke
seed: 1
duration_scale: short
library:
  roots:
    - id: root_main
      path: library
movies: []
series: []
artists:
  - id: artist_north
    name: North Index
    layout: artist_album_disc
    track_naming: track_number_title
    albums:
      - id: album_winter
        title: Winter Index
        release_year: 2024
        discs:
          - id: disc_one
            disc_number: 1
            tracks:
              - id: track_one
                track_number: 1
                title: Opening
                performers:
                  - North Index
                variants:
                  - id: variant_track
                    label: Lossless
                    bundle:
                      id: bundle_track
                      assets:
                        - id: asset_track
                          role: main
                          container: {container}
                          duration_seconds: 2.0
                          audio:
                            - source: {source}
{noise_color_line.rstrip()}
                              codec: {codec}
                              channels: stereo
                              language: eng
                              sample_rate: {sample_rate}
{sample_format_line.rstrip()}
timeline: []
""",
        encoding="utf-8",
    )


def _write_movie_scenario(
    path: Path,
    *,
    audio_codec: str = "aac",
    video_source: str = "color_bars",
    video_codec: str = "h264",
    video_resolution: str = "sd",
    vfr_cadence: str | None = None,
    field_order: str | None = None,
    color_space: str | None = None,
    color_range: str | None = None,
    hdr_mode: str | None = None,
) -> None:
    vfr_line = f"                vfr_cadence: {vfr_cadence}\n" if vfr_cadence else ""
    field_order_line = f"                field_order: {field_order}\n" if field_order else ""
    color_space_line = f"                color_space: {color_space}\n" if color_space else ""
    color_range_line = f"                color_range: {color_range}\n" if color_range else ""
    hdr_mode_line = f"                hdr_mode: {hdr_mode}\n" if hdr_mode else ""
    path.write_text(
        f"""schema_version: 19
scenario_id: movie-validation-smoke
seed: 1
duration_scale: short
library:
  roots:
    - id: root_main
      path: library
movies:
  - id: movie_smoke
    title: Movie Validation Smoke Test
    layout: movie_flat
    variants:
      - id: variant_sd
        label: sd
        bundle:
          id: bundle_sd
          assets:
            - id: asset_sd_main
              role: main
              container: mkv
              duration_seconds: 2.0
              video:
                source: {video_source}
                codec: {video_codec}
                resolution: {video_resolution}
{vfr_line.rstrip()}
{field_order_line.rstrip()}
{color_space_line.rstrip()}
{color_range_line.rstrip()}
{hdr_mode_line.rstrip()}
              audio:
                - source: sine
                  codec: {audio_codec}
                  channels: stereo
                  language: eng
series: []
artists: []
timeline: []
""",
        encoding="utf-8",
    )


def _write_resolution_switch_scenario(
    path: Path,
    *,
    container: str = "ts",
    video_source: str = "color_bars",
    video_codec: str = "h264",
    video_resolution: str = "sd",
    audio: bool = False,
    subtitles: bool = False,
    vfr_cadence: str | None = None,
    field_order: str | None = None,
    color_space: str | None = None,
    color_range: str | None = None,
    hdr_mode: str | None = None,
) -> None:
    optional_video_lines = []
    if vfr_cadence is not None:
        optional_video_lines.append(f"                vfr_cadence: {vfr_cadence}")
    if field_order is not None:
        optional_video_lines.append(f"                field_order: {field_order}")
    if color_space is not None:
        optional_video_lines.append(f"                color_space: {color_space}")
    if color_range is not None:
        optional_video_lines.append(f"                color_range: {color_range}")
    if hdr_mode is not None:
        optional_video_lines.append(f"                hdr_mode: {hdr_mode}")
    optional_video = "\n".join(optional_video_lines)
    optional_video = f"\n{optional_video}" if optional_video else ""
    audio_block = (
        """              audio:
                - source: sine
                  codec: aac
                  channels: stereo
                  language: eng
"""
        if audio
        else ""
    )
    subtitles_block = (
        """              subtitles:
                - source: generated_srt
                  codec: srt
                  language: eng
                  mode: embedded
"""
        if subtitles
        else ""
    )
    path.write_text(
        f"""schema_version: 19
scenario_id: resolution-switch-validation-smoke
seed: 1
duration_scale: short
library:
  roots:
    - id: root_main
      path: library
movies:
  - id: movie_switch
    title: Resolution Switch Validation Smoke Test
    layout: movie_flat
    variants:
      - id: variant_switch
        label: sd-to-hd
        bundle:
          id: bundle_switch
          assets:
            - id: asset_switch_main
              role: main
              container: {container}
              duration_seconds: 2.0
              video:
                source: {video_source}
                codec: {video_codec}
                resolution: {video_resolution}
                resolution_sequence: sd_to_hd{optional_video}
{audio_block.rstrip()}
{subtitles_block.rstrip()}
series: []
artists: []
timeline: []
""",
        encoding="utf-8",
    )


def _first_materialize_issue_path(path: Path) -> str:
    report = run_validation(prepare_run_input(path))
    assert report.ok is False
    issue = next(issue for issue in report.issues if issue.code == codes.E_MATERIALIZE_UNSUPPORTED)
    assert issue.path is not None
    return issue.path


def test_resolution_switch_video_validates_clean(tmp_path: Path) -> None:
    scenario = tmp_path / "resolution-switch.yaml"
    _write_resolution_switch_scenario(scenario)

    report = run_validation(prepare_run_input(scenario))

    assert report.ok is True
    assert report.issues == []


@pytest.mark.parametrize(
    "case",
    [
        ResolutionSwitchCase(
            name="container",
            container="mkv",
            field_suffix=".container",
        ),
        ResolutionSwitchCase(
            name="codec",
            video_codec="hevc",
            field_suffix=".video.codec",
        ),
        ResolutionSwitchCase(
            name="source",
            video_source="mandelbrot",
            field_suffix=".video.source",
        ),
        ResolutionSwitchCase(
            name="resolution",
            video_resolution="hd",
            field_suffix=".video.resolution",
        ),
        ResolutionSwitchCase(
            name="audio",
            audio=True,
            field_suffix=".audio",
        ),
        ResolutionSwitchCase(
            name="subtitles",
            subtitles=True,
            field_suffix=".subtitles",
        ),
        ResolutionSwitchCase(
            name="vfr",
            vfr_cadence="24_to_30",
            field_suffix=".video.vfr_cadence",
        ),
        ResolutionSwitchCase(
            name="interlaced",
            field_order="top_field_first",
            field_suffix=".video.field_order",
        ),
        ResolutionSwitchCase(
            name="color-space",
            color_space="bt709",
            field_suffix=".video.color_space",
        ),
        ResolutionSwitchCase(
            name="color-range",
            color_range="full",
            field_suffix=".video.color_range",
        ),
        ResolutionSwitchCase(
            name="hdr",
            hdr_mode="hdr10",
            field_suffix=".video.hdr_mode",
        ),
    ],
)
def test_resolution_switch_video_rejects_unsupported_combinations(
    tmp_path: Path,
    case: ResolutionSwitchCase,
) -> None:
    scenario = tmp_path / f"resolution-switch-{case.name}.yaml"
    _write_resolution_switch_scenario(
        scenario,
        container=case.container,
        video_source=case.video_source,
        video_codec=case.video_codec,
        video_resolution=case.video_resolution,
        audio=case.audio,
        subtitles=case.subtitles,
        vfr_cadence=case.vfr_cadence,
        field_order=case.field_order,
        color_space=case.color_space,
        color_range=case.color_range,
        hdr_mode=case.hdr_mode,
    )

    issue_path = _first_materialize_issue_path(scenario)

    assert issue_path.endswith(case.field_suffix)


def test_unsupported_video_resolution_names_field(tmp_path: Path) -> None:
    scenario = tmp_path / "materialize-video-resolution-small.yaml"
    _write_movie_scenario(scenario, video_resolution="small")

    report = run_validation(prepare_run_input(scenario))

    assert report.ok is False
    issue = next(issue for issue in report.issues if issue.code == codes.E_MATERIALIZE_UNSUPPORTED)
    assert issue.path is not None
    assert issue.path.endswith(".video.resolution")
    assert "small" in issue.message


def test_unsupported_video_codec_names_field(tmp_path: Path) -> None:
    scenario = tmp_path / "materialize-video-codec-av1.yaml"
    _write_movie_scenario(scenario, video_codec="av1")

    report = run_validation(prepare_run_input(scenario))

    assert report.ok is False
    issue = next(issue for issue in report.issues if issue.code == codes.E_MATERIALIZE_UNSUPPORTED)
    assert issue.path is not None
    assert issue.path.endswith(".video.codec")
    assert "av1" in issue.message


def test_unsupported_video_source_names_field(tmp_path: Path) -> None:
    scenario = tmp_path / "materialize-video-source-noise.yaml"
    _write_movie_scenario(scenario, video_source="noise")

    report = run_validation(prepare_run_input(scenario))

    assert report.ok is False
    issue = next(issue for issue in report.issues if issue.code == codes.E_MATERIALIZE_UNSUPPORTED)
    assert issue.path is not None
    assert issue.path.endswith(".video.source")
    assert "noise" in issue.message


def test_movie_audio_codec_flac_is_unsupported(tmp_path: Path) -> None:
    scenario = tmp_path / "materialize-movie-audio-flac.yaml"
    _write_movie_scenario(scenario, audio_codec="flac")

    report = run_validation(prepare_run_input(scenario))

    assert report.ok is False
    issue = next(issue for issue in report.issues if issue.code == codes.E_MATERIALIZE_UNSUPPORTED)
    assert issue.path is not None
    assert issue.path.endswith(".audio[0].codec")
    assert "flac" in issue.message


def test_hevc_sd_mkv_aac_validates_clean(tmp_path: Path) -> None:
    scenario = tmp_path / "hevc.yaml"
    scenario.write_text(
        """schema_version: 19
scenario_id: hevc-validation-smoke
seed: 1
duration_scale: short
library:
  roots:
    - id: root_main
      path: library
movies:
  - id: movie_hevc
    title: HEVC Validation Smoke Test
    layout: movie_flat
    variants:
      - id: variant_sd
        label: sd
        bundle:
          id: bundle_sd
          assets:
            - id: asset_sd_main
              role: main
              container: mkv
              duration_seconds: 2.0
              video:
                source: color_bars
                codec: hevc
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
        encoding="utf-8",
    )

    report = run_validation(prepare_run_input(scenario))

    assert report.ok is True
    assert report.issues == []


def test_vfr_video_cadence_validates_clean(tmp_path: Path) -> None:
    scenario = tmp_path / "vfr.yaml"
    _write_movie_scenario(scenario, vfr_cadence="24_to_30")

    report = run_validation(prepare_run_input(scenario))

    assert report.ok is True
    assert report.issues == []


def test_interlaced_video_field_order_validates_clean(tmp_path: Path) -> None:
    scenario = tmp_path / "interlaced.yaml"
    _write_movie_scenario(scenario, field_order="top_field_first")

    report = run_validation(prepare_run_input(scenario))

    assert report.ok is True
    assert report.issues == []


def test_interlaced_video_rejects_vfr_cadence(tmp_path: Path) -> None:
    scenario = tmp_path / "interlaced-vfr.yaml"
    _write_movie_scenario(
        scenario,
        vfr_cadence="24_to_30",
        field_order="top_field_first",
    )

    report = run_validation(prepare_run_input(scenario))

    assert report.ok is False
    issue = next(issue for issue in report.issues if issue.code == codes.E_MATERIALIZE_UNSUPPORTED)
    assert issue.path is not None
    assert issue.path.endswith(".video.field_order")
    assert "vfr_cadence" in issue.message


def test_interlaced_video_rejects_yaml_numeric_vfr_cadence(tmp_path: Path) -> None:
    scenario = tmp_path / "interlaced-vfr-numeric.yaml"
    _write_movie_scenario(
        scenario,
        vfr_cadence="24_30_60",
        field_order="top_field_first",
    )

    report = run_validation(prepare_run_input(scenario))

    assert report.ok is False
    issue = next(issue for issue in report.issues if issue.code == codes.E_MATERIALIZE_UNSUPPORTED)
    assert issue.path is not None
    assert issue.path.endswith(".video.field_order")
    assert "vfr_cadence" in issue.message


def test_color_signaling_validates_clean(tmp_path: Path) -> None:
    scenario = tmp_path / "color-signaling.yaml"
    _write_movie_scenario(scenario, color_space="bt709", color_range="full")

    report = run_validation(prepare_run_input(scenario))

    assert report.ok is True
    assert report.issues == []


def test_hdr_signaling_validates_clean(tmp_path: Path) -> None:
    scenario = tmp_path / "hdr.yaml"
    _write_movie_scenario(scenario, video_codec="hevc", hdr_mode="hdr10")

    report = run_validation(prepare_run_input(scenario))

    assert report.ok is True
    assert report.issues == []


def test_hdr_signaling_rejects_h264(tmp_path: Path) -> None:
    scenario = tmp_path / "hdr-h264.yaml"
    _write_movie_scenario(scenario, video_codec="h264", hdr_mode="hdr10")

    report = run_validation(prepare_run_input(scenario))

    assert report.ok is False
    issue = next(issue for issue in report.issues if issue.code == codes.E_MATERIALIZE_UNSUPPORTED)
    assert issue.path is not None
    assert issue.path.endswith(".video.hdr_mode")
    assert "HEVC" in issue.message


def test_hdr_signaling_rejects_non_bt2020_color_space(tmp_path: Path) -> None:
    scenario = tmp_path / "hdr-bt709.yaml"
    _write_movie_scenario(
        scenario,
        video_codec="hevc",
        color_space="bt709",
        hdr_mode="hdr10",
    )

    report = run_validation(prepare_run_input(scenario))

    assert report.ok is False
    issue = next(issue for issue in report.issues if issue.code == codes.E_MATERIALIZE_UNSUPPORTED)
    assert issue.path is not None
    assert issue.path.endswith(".video.color_space")
    assert "bt2020" in issue.message


def test_hdr_signaling_rejects_full_color_range(tmp_path: Path) -> None:
    scenario = tmp_path / "hdr-full-range.yaml"
    _write_movie_scenario(
        scenario,
        video_codec="hevc",
        color_range="full",
        hdr_mode="hdr10",
    )

    report = run_validation(prepare_run_input(scenario))

    assert report.ok is False
    issue = next(issue for issue in report.issues if issue.code == codes.E_MATERIALIZE_UNSUPPORTED)
    assert issue.path is not None
    assert issue.path.endswith(".video.color_range")
    assert "limited" in issue.message


def test_hdr_signaling_rejects_vfr_cadence(tmp_path: Path) -> None:
    scenario = tmp_path / "hdr-vfr.yaml"
    _write_movie_scenario(
        scenario,
        video_codec="hevc",
        vfr_cadence="24_to_30",
        hdr_mode="hdr10",
    )

    report = run_validation(prepare_run_input(scenario))

    assert report.ok is False
    issue = next(issue for issue in report.issues if issue.code == codes.E_MATERIALIZE_UNSUPPORTED)
    assert issue.path is not None
    assert issue.path.endswith(".video.hdr_mode")
    assert "vfr_cadence" in issue.message


def test_hdr_signaling_rejects_field_order(tmp_path: Path) -> None:
    scenario = tmp_path / "hdr-interlaced.yaml"
    _write_movie_scenario(
        scenario,
        video_codec="hevc",
        field_order="top_field_first",
        hdr_mode="hdr10",
    )

    report = run_validation(prepare_run_input(scenario))

    assert report.ok is False
    issue = next(issue for issue in report.issues if issue.code == codes.E_MATERIALIZE_UNSUPPORTED)
    assert issue.path is not None
    assert issue.path.endswith(".video.hdr_mode")
    assert "field_order" in issue.message


def test_audio_only_flac_track_validates_clean(tmp_path: Path) -> None:
    scenario = tmp_path / "track-flac.yaml"
    _write_track_scenario(scenario, container="flac", codec="flac")

    report = run_validation(prepare_run_input(scenario))

    assert report.ok is True
    assert report.issues == []


def test_audio_only_mp3_track_validates_clean(tmp_path: Path) -> None:
    scenario = tmp_path / "track-mp3.yaml"
    _write_track_scenario(scenario, container="mp3", codec="mp3")

    report = run_validation(prepare_run_input(scenario))

    assert report.ok is True
    assert report.issues == []


def test_audio_only_m4a_track_validates_clean(tmp_path: Path) -> None:
    scenario = tmp_path / "track-m4a.yaml"
    _write_track_scenario(scenario, container="m4a", codec="aac")

    report = run_validation(prepare_run_input(scenario))

    assert report.ok is True
    assert report.issues == []


def test_audio_only_noise_wav_pcm_float_validates_clean(tmp_path: Path) -> None:
    scenario = tmp_path / "track-noise-wav.yaml"
    _write_track_scenario(
        scenario,
        container="wav",
        codec="pcm_f32le",
        source="noise",
        noise_color="pink",
        sample_rate=96000,
        sample_format="flt",
    )

    report = run_validation(prepare_run_input(scenario))

    assert report.ok is True
    assert report.issues == []


@pytest.mark.parametrize(
    ("container", "codec", "sample_rate", "sample_format", "field_suffix"),
    [
        ("mp3", "mp3", 96000, None, ".audio[0].sample_rate"),
        ("m4a", "aac", 48000, "s16", ".audio[0].sample_format"),
        ("flac", "flac", 48000, "flt", ".audio[0].sample_format"),
        ("wav", "pcm_s16le", 48000, "flt", ".audio[0].sample_format"),
    ],
)
def test_audio_only_rejects_unsupported_sample_rate_or_format(
    tmp_path: Path,
    container: str,
    codec: str,
    sample_rate: int,
    sample_format: str | None,
    field_suffix: str,
) -> None:
    scenario = tmp_path / f"track-{container}-{codec}.yaml"
    _write_track_scenario(
        scenario,
        container=container,
        codec=codec,
        sample_rate=sample_rate,
        sample_format=sample_format,
    )

    issue_path = _first_materialize_issue_path(scenario)

    assert issue_path.endswith(field_suffix)
