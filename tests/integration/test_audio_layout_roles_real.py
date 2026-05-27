"""Real-tool integration coverage for expanded audio layouts and roles."""

from __future__ import annotations

from pathlib import Path

import pytest

from chaos_librarian.contract.content_sources import ContentTrackKind
from chaos_librarian.contract.manifest import Manifest, ProbedStream, StreamKind
from chaos_librarian.contract.materialization import Outcome
from chaos_librarian.materializer.run import materialize_scenario
from chaos_librarian.materializer.tooling.capabilities import MIN_VERSIONS, detect_capabilities
from tests.integration.conftest import _load_current_manifest, _load_materialization_report

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "scenarios"


def _ffmpeg_meets_minimum() -> bool:
    caps = detect_capabilities()
    return caps.ffmpeg.meets_minimum and caps.ffprobe.meets_minimum


pytestmark = pytest.mark.skipif(
    not _ffmpeg_meets_minimum(),
    reason=f"ffmpeg/ffprobe >= {MIN_VERSIONS['ffmpeg']} not available",
)


def _audio_streams_for(manifest: Manifest, asset_id: str) -> list[ProbedStream]:
    version = next(version for version in manifest.versions if version.asset_id == asset_id)
    assert version.probed is not None
    return [stream for stream in version.probed.streams if stream.kind == StreamKind.AUDIO]


def test_audio_layout_role_fixture_materializes_probe_visible_tracks(tmp_path: Path) -> None:
    out = tmp_path / "audio-layout-roles"

    artifacts = materialize_scenario(FIXTURE_DIR / "audio-layout-roles.yaml", out)

    assert artifacts.materialization_report.outcome is Outcome.SUCCESS
    manifest = _load_current_manifest(out)
    movie_streams = _audio_streams_for(manifest, "asset_audio_roles_movie")
    assert [
        (stream.channels, stream.channel_layout, stream.language, stream.title, stream.role)
        for stream in movie_streams
    ] == [
        (4, "4.0", "eng", "Main Audio", "main"),
        (3, "3.0", "eng", "Commentary", "commentary"),
        (2, "stereo", "spa", "Alternate Audio", "alternate"),
    ]

    track_streams = _audio_streams_for(manifest, "asset_audio_roles_track")
    assert [(stream.codec, stream.channels, stream.channel_layout) for stream in track_streams] == [
        ("flac", 7, "6.1")
    ]

    report = _load_materialization_report(out)
    track_indexes_by_asset: dict[str, list[int | None]] = {}
    for source in report.content_sources:
        if source.track_kind != ContentTrackKind.AUDIO:
            continue
        track_indexes_by_asset.setdefault(source.asset_id, []).append(source.track_index)
    assert track_indexes_by_asset["asset_audio_roles_movie"] == [0, 1, 2]
    assert track_indexes_by_asset["asset_audio_roles_track"] == [0]
