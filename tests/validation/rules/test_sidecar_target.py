"""Tests for rules/sidecar_target.py — 3 codes share one projection."""

from __future__ import annotations

from chaos_librarian.scenario_io import LineIndex
from chaos_librarian.validation.codes import (
    E_SIDECAR_KIND_MISMATCH,
    E_SIDECAR_PATH_COLLISION,
    E_SIDECAR_TARGET_UNKNOWN,
)
from chaos_librarian.validation.pipeline import IssueCollector
from chaos_librarian.validation.rules.sidecar_target import rule_sidecar_target


def _run(raw):
    collector = IssueCollector()
    rule_sidecar_target(raw, LineIndex(), collector)
    return collector.issues


def _minimal(timeline, *, asset_subtitles=None):
    """Build a raw dict for one asset with optional declared subtitles."""
    subtitles = asset_subtitles or []
    return {
        "schema_version": 9,
        "scenario_id": "sc",
        "seed": 1,
        "duration_scale": "short",
        "library": {"roots": [{"id": "r0", "path": "library/r0"}]},
        "works": [
            {
                "id": "w0",
                "title": "T",
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
                                        {"codec": "aac", "channels": "stereo", "language": "eng"}
                                    ],
                                    "subtitles": subtitles,
                                }
                            ],
                        },
                    }
                ],
            }
        ],
        "timeline": timeline,
    }


def test_remove_sidecar_unknown_path():
    raw = _minimal(
        [
            {
                "id": "e0",
                "at": "1s",
                "action": "remove_sidecar",
                "target": "a0",
                "sidecar_path": "missing.srt",
            },
        ]
    )
    issues = _run(raw)
    assert any(i.code == E_SIDECAR_TARGET_UNKNOWN for i in issues)


def test_update_sidecar_unknown_path():
    raw = _minimal(
        [
            {
                "id": "e0",
                "at": "1s",
                "action": "update_sidecar",
                "target": "a0",
                "sidecar_path": "missing.srt",
            },
        ]
    )
    issues = _run(raw)
    assert any(i.code == E_SIDECAR_TARGET_UNKNOWN for i in issues)


def test_embed_subtitle_unknown_sidecar_path():
    raw = _minimal(
        [
            {
                "id": "e0",
                "at": "1s",
                "action": "embed_subtitle",
                "target": "a0",
                "sidecar_path": "missing.srt",
            },
        ]
    )
    issues = _run(raw)
    assert any(i.code == E_SIDECAR_TARGET_UNKNOWN for i in issues)


def test_embed_subtitle_against_declared_subtitle_valid():
    raw = _minimal(
        timeline=[
            {
                "id": "e0",
                "at": "1s",
                "action": "embed_subtitle",
                "target": "a0",
                "sidecar_path": "a0.eng.srt",
            },
        ],
        asset_subtitles=[
            {"codec": "srt", "language": "eng", "mode": "sidecar"},
        ],
    )
    issues = _run(raw)
    # Declared subtitle is in the projection at <asset_id>.<language>.srt
    # with kind=subtitle — embed should be accepted.
    assert not any(i.code in {E_SIDECAR_TARGET_UNKNOWN, E_SIDECAR_KIND_MISMATCH} for i in issues)


def test_embed_subtitle_against_poster_sidecar():
    raw = _minimal(
        [
            {
                "id": "e_cs",
                "at": "1s",
                "action": "create_sidecar",
                "target": "a0",
                "to": "a0.poster.png",
                "kind": "poster",
            },
            {
                "id": "e_es",
                "at": "2s",
                "action": "embed_subtitle",
                "target": "a0",
                "sidecar_path": "a0.poster.png",
            },
        ]
    )
    issues = _run(raw)
    assert any(i.code == E_SIDECAR_KIND_MISMATCH for i in issues)


def test_extract_subtitle_to_collides_with_declared_subtitle():
    raw = _minimal(
        timeline=[
            {
                "id": "e0",
                "at": "1s",
                "action": "extract_subtitle",
                "target": "a0",
                "to": "a0.eng.srt",
                "language": "eng",
            },
        ],
        asset_subtitles=[
            {"codec": "srt", "language": "eng", "mode": "sidecar"},
        ],
    )
    issues = _run(raw)
    assert any(i.code == E_SIDECAR_PATH_COLLISION for i in issues)


def test_extract_subtitle_to_collides_with_created_sidecar():
    raw = _minimal(
        [
            {
                "id": "e_cs",
                "at": "1s",
                "action": "create_sidecar",
                "target": "a0",
                "to": "a0.spa.srt",
                "language": "spa",
            },
            {
                "id": "e_xs",
                "at": "2s",
                "action": "extract_subtitle",
                "target": "a0",
                "to": "a0.spa.srt",
                "language": "spa",
            },
        ]
    )
    issues = _run(raw)
    assert any(i.code == E_SIDECAR_PATH_COLLISION for i in issues)


def test_extract_subtitle_to_after_remove_valid():
    # Path freed by remove_sidecar should be reusable.
    raw = _minimal(
        timeline=[
            {
                "id": "e_rs",
                "at": "1s",
                "action": "remove_sidecar",
                "target": "a0",
                "sidecar_path": "a0.eng.srt",
            },
            {
                "id": "e_xs",
                "at": "2s",
                "action": "extract_subtitle",
                "target": "a0",
                "to": "a0.eng.srt",
                "language": "eng",
            },
        ],
        asset_subtitles=[
            {"codec": "srt", "language": "eng", "mode": "sidecar"},
        ],
    )
    issues = _run(raw)
    # remove freed the slot; extract should not collide.
    assert not any(i.code == E_SIDECAR_PATH_COLLISION for i in issues)


def test_create_subtitle_overrides_declared_at_different_path_then_embed_declared_path_emits_E_SIDECAR_TARGET_UNKNOWN():  # noqa: E501
    """Engine drops any prior subtitle row matching (asset, language) regardless of path.

    Without language-based dedup in the validator's projection, a
    scenario that declares ``a0.eng.srt``, calls ``create_sidecar`` for
    the same ``(asset_id, language)`` at a different path, and then
    ``embed_subtitle`` on the old declared path validates clean — only
    to crash the engine with a bare ``KeyError``. PR #63 adversarial
    review finding #2.
    """
    raw = _minimal(
        timeline=[
            {
                "id": "e_cs",
                "at": "1s",
                "action": "create_sidecar",
                "target": "a0",
                "to": "movies/a0/en.srt",
                "language": "eng",
                "kind": "subtitle",
            },
            {
                "id": "e_es",
                "at": "2s",
                "action": "embed_subtitle",
                "target": "a0",
                "sidecar_path": "a0.eng.srt",
            },
        ],
        asset_subtitles=[
            {"codec": "srt", "language": "eng", "mode": "sidecar"},
        ],
    )
    issues = _run(raw)
    assert any(i.code == E_SIDECAR_TARGET_UNKNOWN for i in issues)


def test_embed_subtitle_consumes_sidecar_then_subsequent_remove_unknown():
    raw = _minimal(
        timeline=[
            {
                "id": "e_es",
                "at": "1s",
                "action": "embed_subtitle",
                "target": "a0",
                "sidecar_path": "a0.eng.srt",
            },
            {
                "id": "e_rs",
                "at": "2s",
                "action": "remove_sidecar",
                "target": "a0",
                "sidecar_path": "a0.eng.srt",
            },
        ],
        asset_subtitles=[
            {"codec": "srt", "language": "eng", "mode": "sidecar"},
        ],
    )
    issues = _run(raw)
    # embed consumed the sidecar; the subsequent remove finds nothing.
    assert any(i.code == E_SIDECAR_TARGET_UNKNOWN for i in issues)
