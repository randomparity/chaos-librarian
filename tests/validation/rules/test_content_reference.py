"""Tests for rules/content_reference.py."""

from __future__ import annotations

from chaos_librarian.scenario_io import LineIndex
from chaos_librarian.validation.codes import E_TARGET_UNKNOWN
from chaos_librarian.validation.pipeline import IssueCollector
from chaos_librarian.validation.rules.content_reference import rule_content_reference


def _run(raw: dict[str, object]) -> list:
    collector = IssueCollector()
    rule_content_reference(raw, LineIndex(), collector)
    return collector.issues


def _asset(asset_id: str, **extra: object) -> dict[str, object]:
    return {
        "id": asset_id,
        "role": "primary_video",
        "container": "mkv",
        "duration_seconds": 12,
        "video": {"source": "mandelbrot", "codec": "h264", "resolution": "1080p"},
        "audio": [{"codec": "aac", "channels": "stereo", "language": "eng"}],
        "subtitles": [],
        **extra,
    }


def _scenario(assets: list[dict[str, object]]) -> dict[str, object]:
    return {
        "schema_version": 25,
        "scenario_id": "sc",
        "seed": 1,
        "duration_scale": "short",
        "library": {"roots": [{"id": "r0", "path": "library/r0"}]},
        "movies": [
            {
                "id": "movie_t",
                "title": "T",
                "layout": "movie_flat",
                "variants": [
                    {
                        "id": "v0",
                        "label": "l",
                        "bundle": {"id": "b0", "assets": assets},
                    }
                ],
            }
        ],
        "series": [],
        "artists": [],
        "timeline": [],
    }


def test_valid_earlier_reference_passes() -> None:
    raw = _scenario([_asset("a1"), _asset("a2", same_content_as="a1")])
    assert _run(raw) == []


def test_valid_collision_reference_passes() -> None:
    raw = _scenario([_asset("a1"), _asset("a2", hash_collision_with="a1", collision_prefix_len=8)])
    assert _run(raw) == []


def test_unknown_same_content_reference_rejected() -> None:
    raw = _scenario([_asset("a1"), _asset("a2", same_content_as="nope")])
    issues = _run(raw)
    assert [i.code for i in issues] == [E_TARGET_UNKNOWN]
    assert issues[0].path is not None
    assert issues[0].path.endswith("same_content_as")


def test_unknown_collision_reference_rejected() -> None:
    raw = _scenario(
        [_asset("a1"), _asset("a2", hash_collision_with="nope", collision_prefix_len=8)]
    )
    issues = _run(raw)
    assert [i.code for i in issues] == [E_TARGET_UNKNOWN]
    assert issues[0].path is not None
    assert issues[0].path.endswith("hash_collision_with")


def test_self_reference_rejected() -> None:
    raw = _scenario([_asset("a1", same_content_as="a1")])
    issues = _run(raw)
    assert [i.code for i in issues] == [E_TARGET_UNKNOWN]


def test_forward_reference_rejected() -> None:
    raw = _scenario([_asset("a1", same_content_as="a2"), _asset("a2")])
    issues = _run(raw)
    assert [i.code for i in issues] == [E_TARGET_UNKNOWN]


def test_collision_forward_reference_rejected() -> None:
    raw = _scenario([_asset("a1", hash_collision_with="a2", collision_prefix_len=8), _asset("a2")])
    issues = _run(raw)
    assert [i.code for i in issues] == [E_TARGET_UNKNOWN]
