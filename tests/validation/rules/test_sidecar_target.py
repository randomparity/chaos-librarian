"""Tests for rules/sidecar_target.py — 3 codes share one projection."""

from __future__ import annotations

from typing import cast

from chaos_librarian.scenario_io import LineIndex
from chaos_librarian.validation.codes import (
    E_MATERIALIZE_UNSUPPORTED,
    E_SIDECAR_KIND_MISMATCH,
    E_SIDECAR_PATH_COLLISION,
    E_SIDECAR_TARGET_UNKNOWN,
)
from chaos_librarian.validation.pipeline import IssueCollector
from chaos_librarian.validation.rules.sidecar_target import rule_sidecar_target

DECLARED_SIDECAR_PATH = "library/r0/T - l.eng.srt"
DECLARED_ASS_SIDECAR_PATH = "library/r0/T - l.jpn.ass"
SERIES_SIDECAR_PATH = "TV/Starline/Season 01/Starline - S01E01 - Pilot - HD.eng.srt"
REN_NUMBERED_SIDECAR_PATH = "TV/Starline/Season 01/Starline - S01E02 - Pilot - HD.eng.srt"
REN_NUMBERED_ASS_SIDECAR_PATH = "TV/Starline/Season 01/Starline - S01E02 - Pilot - HD.jpn.ass"


def _run(raw):
    collector = IssueCollector()
    rule_sidecar_target(raw, LineIndex(), collector)
    return collector.issues


def _minimal(timeline, *, asset_subtitles=None):
    """Build a raw dict for one asset with optional declared subtitles."""
    subtitles = asset_subtitles or []
    return {
        "schema_version": 30,
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
        "series": [],
        "artists": [],
        "timeline": timeline,
    }


def _series_asset(raw: dict[str, object]) -> dict[str, object]:
    series_items = cast("list[dict[str, object]]", raw["series"])
    season_items = cast("list[dict[str, object]]", series_items[0]["seasons"])
    episode_items = cast("list[dict[str, object]]", season_items[0]["episodes"])
    variant_items = cast("list[dict[str, object]]", episode_items[0]["variants"])
    bundle = cast("dict[str, object]", variant_items[0]["bundle"])
    assets = cast("list[dict[str, object]]", bundle["assets"])
    return assets[0]


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
                "sidecar_path": DECLARED_SIDECAR_PATH,
            },
        ],
        asset_subtitles=[
            {"codec": "srt", "language": "eng", "mode": "sidecar"},
        ],
    )
    issues = _run(raw)
    # Declared subtitle is in the projection at the rendered media stem
    # with kind=subtitle, so embed should be accepted.
    assert not any(i.code in {E_SIDECAR_TARGET_UNKNOWN, E_SIDECAR_KIND_MISMATCH} for i in issues)


def test_non_default_declared_subtitle_recipe_rejects_update_sidecar():
    raw = _minimal(
        timeline=[
            {
                "id": "e0",
                "at": "1s",
                "action": "update_sidecar",
                "target": "a0",
                "sidecar_path": DECLARED_ASS_SIDECAR_PATH,
            },
        ],
        asset_subtitles=[
            {
                "codec": "ass",
                "source": "styled_ass",
                "language": "jpn",
                "mode": "sidecar",
            },
        ],
    )

    issues = _run(raw)

    assert any(i.code == E_MATERIALIZE_UNSUPPORTED for i in issues)


def test_non_default_declared_subtitle_recipe_rejects_embed_subtitle():
    raw = _minimal(
        timeline=[
            {
                "id": "e0",
                "at": "1s",
                "action": "embed_subtitle",
                "target": "a0",
                "sidecar_path": DECLARED_ASS_SIDECAR_PATH,
            },
        ],
        asset_subtitles=[
            {
                "codec": "ass",
                "source": "styled_ass",
                "language": "jpn",
                "mode": "sidecar",
            },
        ],
    )

    issues = _run(raw)

    assert any(i.code == E_MATERIALIZE_UNSUPPORTED for i in issues)


def test_hierarchy_rerender_accepts_current_declared_sidecar_path(series_scenario):
    raw = series_scenario(
        timeline=[
            {
                "id": "renumber",
                "at": "1s",
                "action": "renumber_episode",
                "target": "episode_one",
                "episode_number": 2,
            },
            {
                "id": "update",
                "at": "2s",
                "action": "update_sidecar",
                "target": "asset_episode",
                "sidecar_path": REN_NUMBERED_SIDECAR_PATH,
            },
        ]
    )
    asset = _series_asset(raw)
    asset["subtitles"] = [{"codec": "srt", "language": "eng", "mode": "sidecar"}]

    issues = _run(raw)

    assert not any(i.code == E_SIDECAR_TARGET_UNKNOWN for i in issues)


def test_hierarchy_rerender_accepts_current_declared_ass_sidecar_path(series_scenario):
    raw = series_scenario(
        timeline=[
            {
                "id": "renumber",
                "at": "1s",
                "action": "renumber_episode",
                "target": "episode_one",
                "episode_number": 2,
            },
            {
                "id": "remove",
                "at": "2s",
                "action": "remove_sidecar",
                "target": "asset_episode",
                "sidecar_path": REN_NUMBERED_ASS_SIDECAR_PATH,
            },
        ]
    )
    asset = _series_asset(raw)
    asset["subtitles"] = [
        {
            "codec": "ass",
            "source": "styled_ass",
            "language": "jpn",
            "mode": "sidecar",
        }
    ]

    issues = _run(raw)

    assert not any(i.code == E_SIDECAR_TARGET_UNKNOWN for i in issues)


def test_hierarchy_rerender_rejects_stale_declared_sidecar_path(series_scenario):
    raw = series_scenario(
        timeline=[
            {
                "id": "renumber",
                "at": "1s",
                "action": "renumber_episode",
                "target": "episode_one",
                "episode_number": 2,
            },
            {
                "id": "update",
                "at": "2s",
                "action": "update_sidecar",
                "target": "asset_episode",
                "sidecar_path": SERIES_SIDECAR_PATH,
            },
        ]
    )
    asset = _series_asset(raw)
    asset["subtitles"] = [{"codec": "srt", "language": "eng", "mode": "sidecar"}]

    issues = _run(raw)

    assert any(i.code == E_SIDECAR_TARGET_UNKNOWN for i in issues)


def test_hierarchy_rerender_keeps_explicit_sidecar_at_old_rendered_path(series_scenario):
    raw = series_scenario(
        timeline=[
            {
                "id": "create",
                "at": "1s",
                "action": "create_sidecar",
                "target": "asset_episode",
                "to": SERIES_SIDECAR_PATH,
                "language": "eng",
                "kind": "subtitle",
            },
            {
                "id": "renumber",
                "at": "2s",
                "action": "renumber_episode",
                "target": "episode_one",
                "episode_number": 2,
            },
            {
                "id": "update",
                "at": "3s",
                "action": "update_sidecar",
                "target": "asset_episode",
                "sidecar_path": SERIES_SIDECAR_PATH,
            },
        ]
    )

    issues = _run(raw)

    assert not any(i.code == E_SIDECAR_TARGET_UNKNOWN for i in issues)


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


def test_update_sidecar_against_created_poster_sidecar_valid():
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
                "id": "e_us",
                "at": "2s",
                "action": "update_sidecar",
                "target": "a0",
                "sidecar_path": "a0.poster.png",
            },
        ]
    )

    issues = _run(raw)

    assert not any(i.code == E_MATERIALIZE_UNSUPPORTED for i in issues)


def test_extract_subtitle_to_collides_with_declared_subtitle():
    raw = _minimal(
        timeline=[
            {
                "id": "e0",
                "at": "1s",
                "action": "extract_subtitle",
                "target": "a0",
                "to": DECLARED_SIDECAR_PATH,
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
                "sidecar_path": DECLARED_SIDECAR_PATH,
            },
            {
                "id": "e_xs",
                "at": "2s",
                "action": "extract_subtitle",
                "target": "a0",
                "to": DECLARED_SIDECAR_PATH,
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
    scenario that declares a rendered sidecar, calls ``create_sidecar``
    for the same ``(asset_id, language)`` at a different path, and then
    ``embed_subtitle`` on the old declared path validates clean — only to
    crash the engine with a bare ``KeyError``. PR #63 adversarial review
    finding #2.
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
                "sidecar_path": DECLARED_SIDECAR_PATH,
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
                "sidecar_path": DECLARED_SIDECAR_PATH,
            },
            {
                "id": "e_rs",
                "at": "2s",
                "action": "remove_sidecar",
                "target": "a0",
                "sidecar_path": DECLARED_SIDECAR_PATH,
            },
        ],
        asset_subtitles=[
            {"codec": "srt", "language": "eng", "mode": "sidecar"},
        ],
    )
    issues = _run(raw)
    # embed consumed the sidecar; the subsequent remove finds nothing.
    assert any(i.code == E_SIDECAR_TARGET_UNKNOWN for i in issues)
