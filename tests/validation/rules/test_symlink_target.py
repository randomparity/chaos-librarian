"""Tests for rules/symlink_target.py."""

from __future__ import annotations

from chaos_librarian.scenario_io import LineIndex
from chaos_librarian.validation.codes import E_SYMLINK_TARGET_ESCAPE
from chaos_librarian.validation.reporting import IssueCollector
from chaos_librarian.validation.rules.symlink_target import rule_symlink_target_escape


def _run(raw: dict[str, object]) -> list:
    collector = IssueCollector()
    rule_symlink_target_escape(raw, LineIndex(), collector)
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
        "schema_version": 32,
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


def _symlink_asset(asset_id: str, symlink: dict[str, object]) -> dict[str, object]:
    return _asset(asset_id, symlink=symlink)


def test_well_formed_escaping_target_passes() -> None:
    raw = _scenario([_symlink_asset("a1", {"to_run_dir_path": "external-store/clip.mkv"})])
    assert _run(raw) == []


def test_to_asset_form_is_ignored() -> None:
    raw = _scenario([_symlink_asset("a1", {"to_asset": "x"})])
    assert _run(raw) == []


def test_target_inside_library_rejected() -> None:
    raw = _scenario([_symlink_asset("a1", {"to_run_dir_path": "library/x/y.mkv"})])
    issues = _run(raw)
    assert [i.code for i in issues] == [E_SYMLINK_TARGET_ESCAPE]
    assert issues[0].path is not None
    assert issues[0].path.endswith("to_run_dir_path")


def test_target_equal_to_library_rejected() -> None:
    raw = _scenario([_symlink_asset("a1", {"to_run_dir_path": "library"})])
    assert [i.code for i in _run(raw)] == [E_SYMLINK_TARGET_ESCAPE]


def test_target_into_library_via_parent_rejected() -> None:
    raw = _scenario([_symlink_asset("a1", {"to_run_dir_path": "library/../library/x.mkv"})])
    assert [i.code for i in _run(raw)] == [E_SYMLINK_TARGET_ESCAPE]


def test_target_escaping_run_dir_rejected() -> None:
    raw = _scenario([_symlink_asset("a1", {"to_run_dir_path": "../escape.mkv"})])
    assert [i.code for i in _run(raw)] == [E_SYMLINK_TARGET_ESCAPE]


def test_absolute_target_rejected() -> None:
    raw = _scenario([_symlink_asset("a1", {"to_run_dir_path": "/abs/path.mkv"})])
    assert [i.code for i in _run(raw)] == [E_SYMLINK_TARGET_ESCAPE]


def test_target_equal_to_run_dir_rejected() -> None:
    raw = _scenario([_symlink_asset("a1", {"to_run_dir_path": "."})])
    assert [i.code for i in _run(raw)] == [E_SYMLINK_TARGET_ESCAPE]


def test_no_symlink_field_passes() -> None:
    raw = _scenario([_asset("a1")])
    assert _run(raw) == []
