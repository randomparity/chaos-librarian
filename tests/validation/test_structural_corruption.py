"""Structural recipes reject unsupported synthesis before publication."""

import pytest

from chaos_librarian.validation.reporting import IssueCollector
from chaos_librarian.validation.rules.media.structural_corruption import rule_structural_corruption
from chaos_librarian.validation.scenario_io import LineIndex
from chaos_librarian.validation.semantic import run_semantic_pass


def _raw(asset: dict[str, object], events: list[dict[str, object]]) -> dict[str, object]:
    return {"movies": [{"variants": [{"bundle": {"assets": [asset]}}]}], "timeline": events}


def _asset() -> dict[str, object]:
    return {
        "id": "a",
        "container": "mkv",
        "duration_seconds": 2,
        "video": {"codec": "h264", "resolution": "sd", "source": "color_bars"},
        "audio": [],
    }


def _errors(asset: dict[str, object], events: list[dict[str, object]] | None = None) -> list[str]:
    collector = IssueCollector()
    run_semantic_pass(
        _raw(
            asset,
            events or [{"target": "a", "action": "corrupt_container_header", "region": "mkv_cues"}],
        ),
        LineIndex(),
        collector,
    )
    return [i.message for i in collector.issues if i.code == "E_MATERIALIZE_UNSUPPORTED"]


def test_supported_structural_cell_passes() -> None:
    assert not _errors(_asset())


@pytest.mark.parametrize(
    "change",
    [
        {"container": "webm"},
        {"duration_seconds": 31},
        {"duration_seconds": 0},
        {"video": {"codec": "h264", "resolution": "1080p"}},
        {"video": {"codec": "hevc", "resolution": "sd"}},
        {"import_source": {}},
        {"same_content_as": "other"},
        {"hardlinked_to": "other"},
        {"symlink": {}},
        {"matroska_muxing_profile": "no_cues"},
        {"embedded_chapters": {}},
        {"audio": [{"codec": "aac", "channels": "stereo", "default": True, "forced": False}]},
        {"audio": [{"codec": "aac", "channels": "stereo"}] * 2},
    ],
)
def test_structural_matrix_rejects_unsupported_asset(change: dict[str, object]) -> None:
    assert _errors({**_asset(), **change})


@pytest.mark.parametrize(
    "other",
    [
        "truncate_file",
        "remux_container",
        "edit_metadata",
        "corrupt_container_header",
        "reencode_video",
    ],
)
def test_other_mutations_cannot_invalidate_structural_input(other: str) -> None:
    events: list[dict[str, object]] = [
        {"target": "a", "action": "corrupt_container_header", "region": "mkv_cues"},
        {"target": "a", "action": other},
    ]
    assert _errors(_asset(), events)


@pytest.mark.parametrize(
    ("rate", "channels", "expected"),
    [(44100, "stereo", False), (48000, "stereo", True), (44100, "5.1", True)],
)
def test_mp3_structural_matrix(rate: int, channels: str, expected: bool) -> None:
    asset: dict[str, object] = {
        "id": "a",
        "container": "mp3",
        "duration_seconds": 2,
        "audio": [{"codec": "mp3", "sample_rate": rate, "channels": channels}],
    }
    collector = IssueCollector()
    rule_structural_corruption(
        _raw(
            asset, [{"target": "a", "action": "truncate_file", "boundary": "mp3_after_16_frames"}]
        ),
        LineIndex(),
        collector,
    )
    assert bool(collector.issues) is expected
