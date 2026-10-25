"""Per-rule tests for ``rule_import_source`` and import-asset matrix gating.

Why: an import asset's ``import_source.path`` is the one scenario field that
names a file the materializer READS from outside the library. Validation
proves containment lexically (rules never touch the filesystem): a relative,
non-empty path whose every component passes ``is_safe_path_component`` can
only resolve under the scenario directory. The matrix rule must skip
track-less import assets (bytes carry the properties) but reject declared-
track media mutations targeting them.
"""

from __future__ import annotations

from typing import cast

import pytest

from chaos_librarian.validation.codes import (
    E_IMPORT_SOURCE_INVALID,
    E_MATERIALIZE_UNSUPPORTED,
)
from chaos_librarian.validation.reporting import IssueCollector
from chaos_librarian.validation.rules.media.import_source import rule_import_source
from chaos_librarian.validation.rules.media.materialize_media_matrix import (
    rule_materialize_media_matrix,
)
from chaos_librarian.validation.scenario_io import LineIndex


def _movie_with_import_asset(asset: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": 36,
        "scenario_id": "t",
        "seed": 1,
        "duration_scale": "short",
        "library": {"roots": [{"id": "r", "path": "r"}]},
        "movies": [
            {
                "id": "m",
                "title": "T",
                "layout": "movie_flat",
                "variants": [{"id": "v", "label": "l", "bundle": {"id": "b", "assets": [asset]}}],
            }
        ],
        "series": [],
        "artists": [],
        "timeline": [],
    }


def _import_asset(**overrides) -> dict[str, object]:
    asset: dict[str, object] = {
        "id": "imp-1",
        "role": "main",
        "container": "mkv",
        "duration_seconds": 1,
        "import_source": {"path": "media/imp-1.mkv"},
    }
    asset.update(overrides)
    return asset


def _run_rule(raw: dict[str, object]) -> IssueCollector:
    collector = IssueCollector()
    rule_import_source(raw, LineIndex(), collector)
    return collector


@pytest.mark.parametrize(
    ("label", "bad_path"),
    [
        ("absolute", "/etc/passwd"),
        ("empty", ""),
        ("dot-only", "."),
        ("escape", "media/../../x.mkv"),
        ("backslash-component", "bad\\slash.mkv"),
        ("control-char", "bad\x01.mkv"),
    ],
)
def test_bad_paths_rejected(label: str, bad_path: str) -> None:
    raw = _movie_with_import_asset(_import_asset(import_source={"path": bad_path}))
    collector = _run_rule(raw)
    codes_seen = [issue.code for issue in collector.issues]
    assert E_IMPORT_SOURCE_INVALID in codes_seen, f"{label}: {codes_seen}"


def test_valid_relative_path_passes() -> None:
    collector = _run_rule(_movie_with_import_asset(_import_asset()))
    assert collector.issues == []


def test_non_import_assets_ignored() -> None:
    raw = _movie_with_import_asset(
        {
            "id": "syn-1",
            "role": "main",
            "container": "mkv",
            "duration_seconds": 1,
            "video": {"source": "color_bars", "codec": "h264", "resolution": "sd"},
        }
    )
    collector = _run_rule(raw)
    assert collector.issues == []


# ---- matrix gating ----------------------------------------------------------


def _run_matrix(raw: dict[str, object]) -> IssueCollector:
    collector = IssueCollector()
    rule_materialize_media_matrix(raw, LineIndex(), collector)
    return collector


def _append_event(raw: dict[str, object], event: dict[str, object]) -> None:
    timeline = cast("list[dict[str, object]]", raw["timeline"])
    timeline.append(event)


def test_matrix_skips_trackless_import_asset() -> None:
    """A track-less import asset would otherwise fail must-declare-video."""
    collector = _run_matrix(_movie_with_import_asset(_import_asset()))
    assert collector.issues == []


def test_matrix_rejects_reencode_on_import_asset() -> None:
    raw = _movie_with_import_asset(_import_asset())
    _append_event(
        raw,
        {
            "id": "ev1",
            "at": "0s",
            "action": "reencode_video",
            "target": "imp-1",
            "to": "reencoded.mkv",
            "resolution": "hd",
            "codec": "h264",
        },
    )
    collector = _run_matrix(raw)
    codes_seen = [issue.code for issue in collector.issues]
    assert E_MATERIALIZE_UNSUPPORTED in codes_seen, codes_seen


def test_matrix_allows_file_level_event_on_import_asset() -> None:
    raw = _movie_with_import_asset(_import_asset())
    _append_event(
        raw,
        {
            "id": "ev2",
            "at": "0s",
            "action": "rename_file",
            "target": "imp-1",
            "to": "renamed.mkv",
        },
    )
    collector = _run_matrix(raw)
    assert collector.issues == []
