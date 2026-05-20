"""Tests for the materializer preflight gate.

Sprint 6 narrows the timeline-action gate from Sprint 5's "any timeline
rejected" semantic to an action-set gate: the eight Sprint 6 actions are
allowed, ``add_file`` (Sprint 7) and the media-mutation actions
(``reencode_*``) still raise ``TimelineUnsupportedError`` with code
``E_MATERIALIZE_TIMELINE_UNSUPPORTED`` before phase A allocates a run-dir.
"""

from __future__ import annotations

import pytest

from chaos_librarian.contract.scenario import Scenario
from chaos_librarian.materializer.errors import TimelineUnsupportedError
from chaos_librarian.materializer.preflight import (
    SUPPORTED_S6_ACTIONS,
    preflight_timeline,
)


def _scenario_with_timeline(events: list[tuple[str, str, dict]]) -> Scenario:
    """Build a minimal v4 Scenario whose timeline carries ``events``.

    Each entry is ``(action, target, extra_fields)``; ``extra_fields`` is
    merged into the event dict before validation. Event ids are
    auto-generated as ``ev_0001``, ``ev_0002``, ...  and times are
    monotonic (``0ns``, ``1ns``, ...).
    """
    timeline = [
        {
            "id": f"ev_{index + 1:04d}",
            "at": f"{index}ns",
            "action": action,
            "target": target,
            **extra,
        }
        for index, (action, target, extra) in enumerate(events)
    ]
    return Scenario.model_validate(
        {
            "schema_version": 4,
            "scenario_id": "preflight-test",
            "seed": 1,
            "duration_scale": "short",
            "library": {
                "roots": [
                    {"id": "movies-hd", "path": "library/movies-hd"},
                    {"id": "cold-storage", "path": "library/cold-storage"},
                ],
            },
            "works": [
                {
                    "id": "work_001",
                    "title": "Test Work",
                    "variants": [
                        {
                            "id": "variant_001",
                            "label": "default",
                            "bundle": {
                                "id": "bundle_001",
                                "assets": [
                                    {
                                        "id": "asset_hd_main",
                                        "role": "primary_video",
                                        "container": "mkv",
                                        "duration_seconds": 1,
                                    }
                                ],
                            },
                        }
                    ],
                }
            ],
            "timeline": timeline,
        }
    )


def test_preflight_timeline_accepts_supported_actions() -> None:
    """WHY: the Sprint 6 matrix permits these eight actions; preflight
    must let them through so phase B can execute them."""
    scenario = _scenario_with_timeline(
        [
            ("move_asset", "asset_hd_main", {"to": "movies-hd/new.mkv"}),
            ("rename_file", "asset_hd_main", {"to": "movies-hd/renamed.mkv"}),
            ("archive_file", "asset_hd_main", {}),
            (
                "move_between_roots",
                "asset_hd_main",
                {"from_root_id": "movies-hd", "to_root_id": "cold-storage"},
            ),
        ]
    )
    preflight_timeline(scenario)  # should not raise


def test_preflight_timeline_rejects_add_file() -> None:
    """WHY: ``add_file`` lands in Sprint 7 alongside recipe-driven byte
    synthesis. Until then, preflight must reject it with the
    matrix-rejection error and the gate must fire on the first
    unsupported event so phase A never allocates a run-dir."""
    scenario = _scenario_with_timeline(
        [
            ("delete_file", "asset_hd_main", {}),
            ("add_file", "asset_hd_main", {"to": "movies-hd/new.mkv"}),
        ]
    )
    with pytest.raises(TimelineUnsupportedError) as exc_info:
        preflight_timeline(scenario)
    assert exc_info.value.error_code == "E_MATERIALIZE_TIMELINE_UNSUPPORTED"
    assert exc_info.value.payload["action"] == "add_file"
    supported = exc_info.value.payload["supported"]
    assert isinstance(supported, list)
    assert "add_file" not in supported


def test_preflight_timeline_rejects_reencode_video() -> None:
    """WHY: media-mutation actions remain unsupported in Sprint 6 and the
    matrix-rejection contract applies uniformly across them."""
    scenario = _scenario_with_timeline(
        [
            ("reencode_video", "asset_hd_main", {"resolution": "sd", "codec": "h264"}),
        ]
    )
    with pytest.raises(TimelineUnsupportedError):
        preflight_timeline(scenario)


def test_preflight_timeline_empty_timeline_accepted() -> None:
    """WHY: static scenarios remain valid materialize targets in Sprint 6;
    the action-set gate is a no-op when there are no events."""
    scenario = _scenario_with_timeline([])
    preflight_timeline(scenario)


def test_supported_s6_actions_excludes_add_file_and_reencodes() -> None:
    """WHY: lock the explicit Sprint 6 / Sprint 7 split. ``add_file`` and
    the ``reencode_*`` actions must stay outside the set until their own
    sprint lifts them in."""
    supported_values = {a.value for a in SUPPORTED_S6_ACTIONS}
    assert "add_file" not in supported_values
    assert "reencode_video" not in supported_values
    assert "reencode_audio" not in supported_values
    assert len(SUPPORTED_S6_ACTIONS) == 8
