"""Per-rule tests for static media values materialize can synthesize."""

from __future__ import annotations

from pathlib import Path

from chaos_librarian.validation import codes, prepare_run_input, run_validation


def _write_track_scenario(path: Path, *, container: str, codec: str) -> None:
    path.write_text(
        f"""schema_version: 12
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
                            - source: sine
                              codec: {codec}
                              channels: stereo
                              language: eng
timeline: []
""",
        encoding="utf-8",
    )


def _write_movie_scenario(
    path: Path,
    *,
    video_source: str = "color_bars",
    video_codec: str = "h264",
    video_resolution: str = "sd",
) -> None:
    path.write_text(
        f"""schema_version: 12
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


def test_hevc_sd_mkv_aac_validates_clean(tmp_path: Path) -> None:
    scenario = tmp_path / "hevc.yaml"
    scenario.write_text(
        """schema_version: 12
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
