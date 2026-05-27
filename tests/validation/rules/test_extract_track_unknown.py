"""Tests for rules/extract_track_unknown.py."""

from __future__ import annotations

from chaos_librarian.scenario_io import LineIndex
from chaos_librarian.validation.codes import E_EXTRACT_TRACK_UNKNOWN
from chaos_librarian.validation.pipeline import IssueCollector
from chaos_librarian.validation.rules.extract_track_unknown import (
    rule_extract_track_unknown,
)

EXTRACT_OUTPUT_PATH = "library/r0/T - l.eng.srt"


def _run(raw):
    collector = IssueCollector()
    rule_extract_track_unknown(raw, LineIndex(), collector)
    return collector.issues


def _scenario(timeline, *, asset_subtitles=None):
    return {
        "schema_version": 23,
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
                        "bundle": {
                            "id": "b0",
                            "assets": [
                                {
                                    "id": "a0",
                                    "role": "primary_video",
                                    "container": "mkv",
                                    "duration_seconds": 1.0,
                                    "video": {
                                        "source": "color_bars",
                                        "codec": "h264",
                                        "resolution": "hd",
                                    },
                                    "audio": [
                                        {
                                            "codec": "aac",
                                            "channels": "stereo",
                                            "language": "eng",
                                        }
                                    ],
                                    "subtitles": asset_subtitles or [],
                                }
                            ],
                        },
                    }
                ],
            }
        ],
        "series": [],
        "artists": [],
        "timeline": timeline,
    }


def test_extract_subtitle_on_asset_without_subtitle_track():
    raw = _scenario(
        [
            {
                "id": "e0",
                "at": "1s",
                "action": "extract_subtitle",
                "target": "a0",
                "to": EXTRACT_OUTPUT_PATH,
                "language": "eng",
            },
        ]
    )
    issues = _run(raw)
    assert any(i.code == E_EXTRACT_TRACK_UNKNOWN for i in issues)


def test_extract_subtitle_valid_with_declared_embedded_track():
    raw = _scenario(
        timeline=[
            {
                "id": "e0",
                "at": "1s",
                "action": "extract_subtitle",
                "target": "a0",
                "to": EXTRACT_OUTPUT_PATH,
                "language": "eng",
            },
        ],
        asset_subtitles=[
            {"codec": "srt", "language": "eng", "mode": "embedded"},
        ],
    )
    issues = _run(raw)
    assert not any(i.code == E_EXTRACT_TRACK_UNKNOWN for i in issues)


def test_extract_subtitle_valid_with_declared_sidecar():
    # Sidecar mode also counts — once embedded by a prior embed_subtitle,
    # the track is in the file. For Sprint 7 validation, ANY declared
    # subtitle of either mode is enough to satisfy this rule.
    raw = _scenario(
        timeline=[
            {
                "id": "e0",
                "at": "1s",
                "action": "extract_subtitle",
                "target": "a0",
                "to": EXTRACT_OUTPUT_PATH,
                "language": "eng",
            },
        ],
        asset_subtitles=[
            {"codec": "srt", "language": "eng", "mode": "sidecar"},
        ],
    )
    issues = _run(raw)
    assert not any(i.code == E_EXTRACT_TRACK_UNKNOWN for i in issues)


def test_extract_subtitle_unknown_target_does_not_emit_track_error():
    # Unknown target is rule_target_unknown's job.
    raw = _scenario(
        [
            {
                "id": "e0",
                "at": "1s",
                "action": "extract_subtitle",
                "target": "nonexistent_asset",
                "to": "x.srt",
                "language": "eng",
            },
        ]
    )
    issues = _run(raw)
    # extract_track_unknown silently skips unknown targets.
    assert not any(i.code == E_EXTRACT_TRACK_UNKNOWN for i in issues)
