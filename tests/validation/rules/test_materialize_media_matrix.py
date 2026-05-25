"""Per-rule tests for static media values materialize can synthesize."""

from __future__ import annotations

from pathlib import Path

from chaos_librarian.validation import codes, prepare_run_input, run_validation

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "scenarios"
INVALID_DIR = FIXTURE_DIR / "invalid"


def test_unsupported_video_resolution_names_field() -> None:
    report = run_validation(
        prepare_run_input(INVALID_DIR / "materialize-video-resolution-small.yaml")
    )

    assert report.ok is False
    issue = next(issue for issue in report.issues if issue.code == codes.E_MATERIALIZE_UNSUPPORTED)
    assert issue.path is not None
    assert issue.path.endswith(".video.resolution")
    assert "small" in issue.message


def test_unsupported_video_codec_names_field() -> None:
    report = run_validation(prepare_run_input(INVALID_DIR / "materialize-video-codec-av1.yaml"))

    assert report.ok is False
    issue = next(issue for issue in report.issues if issue.code == codes.E_MATERIALIZE_UNSUPPORTED)
    assert issue.path is not None
    assert issue.path.endswith(".video.codec")
    assert "av1" in issue.message


def test_unsupported_video_source_names_field() -> None:
    report = run_validation(prepare_run_input(INVALID_DIR / "materialize-video-source-noise.yaml"))

    assert report.ok is False
    issue = next(issue for issue in report.issues if issue.code == codes.E_MATERIALIZE_UNSUPPORTED)
    assert issue.path is not None
    assert issue.path.endswith(".video.source")
    assert "noise" in issue.message


def test_hevc_sd_mkv_aac_validates_clean(tmp_path: Path) -> None:
    scenario = tmp_path / "hevc.yaml"
    scenario.write_text(
        """schema_version: 10
scenario_id: hevc-validation-smoke
seed: 1
duration_scale: short
library:
  roots:
    - id: root_main
      path: library
works:
  - id: work_movie
    title: HEVC Validation Smoke Test
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
timeline: []
""",
        encoding="utf-8",
    )

    report = run_validation(prepare_run_input(scenario))

    assert report.ok is True
    assert report.issues == []
