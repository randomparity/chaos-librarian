"""Real-tool integration coverage for MP4 moov atom placement."""

from __future__ import annotations

from pathlib import Path

import pytest

from chaos_librarian.contract.materialization import Outcome
from chaos_librarian.contract.scenario import Mp4MoovPlacement
from chaos_librarian.materializer.run import materialize_scenario
from chaos_librarian.materializer.tooling.capabilities import MIN_VERSIONS, detect_capabilities

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "scenarios"


def _ffmpeg_meets_minimum() -> bool:
    caps = detect_capabilities()
    return caps.ffmpeg.meets_minimum and caps.ffprobe.meets_minimum


pytestmark = pytest.mark.skipif(
    not _ffmpeg_meets_minimum(),
    reason=f"ffmpeg/ffprobe >= {MIN_VERSIONS['ffmpeg']} not available",
)


def _top_level_atom_offsets(path: Path) -> dict[str, int]:
    offsets: dict[str, int] = {}
    file_size = path.stat().st_size
    with path.open("rb") as fh:
        offset = 0
        while offset + 8 <= file_size:
            fh.seek(offset)
            header = fh.read(8)
            if len(header) < 8:
                break
            size = int.from_bytes(header[:4], "big")
            atom = header[4:].decode("ascii", errors="replace")
            offsets.setdefault(atom, offset)
            header_size = 8
            if size == 1:
                extended_size = fh.read(8)
                if len(extended_size) < 8:
                    break
                size = int.from_bytes(extended_size, "big")
                header_size = 16
            elif size == 0:
                break
            if size < header_size:
                raise AssertionError(f"invalid MP4 atom {atom!r} size {size} at {offset}")
            offset += size
    return offsets


def test_mp4_moov_placement_materializes_atom_order(tmp_path: Path) -> None:
    out = tmp_path / "mp4-moov-placement"

    artifacts = materialize_scenario(FIXTURE_DIR / "mp4-moov-placement.yaml", out)

    assert artifacts.materialization_report.outcome is Outcome.SUCCESS
    start_path = out / "library" / "movies" / "Moov Placement - start.mp4"
    end_path = out / "library" / "movies" / "Moov Placement - end.mp4"
    start_offsets = _top_level_atom_offsets(start_path)
    end_offsets = _top_level_atom_offsets(end_path)
    assert start_offsets["moov"] < start_offsets["mdat"]
    assert end_offsets["mdat"] < end_offsets["moov"]

    placements = {
        item.asset_id: item.mp4_moov_placement
        for item in artifacts.materialization_report.materialized
    }
    assert placements["asset_moov_start"] is Mp4MoovPlacement.MOOV_AT_START
    assert placements["asset_moov_end"] is Mp4MoovPlacement.MOOV_AT_END
