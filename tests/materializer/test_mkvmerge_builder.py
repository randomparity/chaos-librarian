"""mkvmerge argv builder coverage."""

from __future__ import annotations

from pathlib import Path

from chaos_librarian.contract.scenario import MatroskaMuxingProfile
from chaos_librarian.materializer.tooling.mkvmerge import build_mkvmerge_command


def test_no_cues_command_emits_deterministic_common_args(tmp_path: Path) -> None:
    input_path = tmp_path / "in.mkv"
    output_path = tmp_path / "out.mkv"

    argv = build_mkvmerge_command(
        input_path=input_path,
        output_path=output_path,
        container="mkv",
        profile=MatroskaMuxingProfile.NO_CUES,
        deterministic_seed=138,
    )

    assert argv[:2] == ["mkvmerge", "--quiet"]
    assert argv[argv.index("--deterministic") + 1] == "138"
    assert "--no-date" in argv
    assert "--disable-track-statistics-tags" in argv
    assert "--no-cues" in argv
    assert argv[argv.index("-o") + 1] == str(output_path)
    assert argv[-1] == str(input_path)


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
