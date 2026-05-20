"""Tests for the 4 sidecar-touching handlers added in Sprint 7.

embed_subtitle, extract_subtitle, remove_sidecar, update_sidecar.
"""

from __future__ import annotations

import uuid

from chaos_librarian.contract.scenario import Scenario
from chaos_librarian.determinism import IdAllocator, TraceRecorder
from chaos_librarian.engine.events import apply_event
from chaos_librarian.engine.resolution import resolve_timeline
from chaos_librarian.engine.state import build_initial_state

_RUN_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")


def _scenario_with_subtitle_declared(timeline: list[dict[str, object]]) -> Scenario:
    """Asset declares one English subtitle as a sidecar. Phase A would
    write it at ``a0.eng.srt``; the engine doesn't pre-populate it (only
    create_sidecar / extract_subtitle do)."""
    return Scenario.model_validate(
        {
            "schema_version": 5,
            "scenario_id": "sidecar_tests",
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
                            "label": "hd",
                            "bundle": {
                                "id": "b0",
                                "assets": [
                                    {
                                        "id": "a0",
                                        "role": "primary_video",
                                        "container": "mkv",
                                        "duration_seconds": 1,
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
                                        "subtitles": [
                                            {"codec": "srt", "language": "eng", "mode": "sidecar"}
                                        ],
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


class TestEmbedSubtitleHandler:
    """embed_subtitle allocates a new version, removes the sidecar from state.

    WHY: embedding consumes the sidecar file (materializer unlinks it).
    The manifest must reflect that — both the new asset version AND the
    absence of the sidecar row.
    """

    def test_embed_allocates_new_version(self) -> None:
        scenario = _scenario_with_subtitle_declared(
            [
                {
                    "id": "e_cs",
                    "at": "1s",
                    "action": "create_sidecar",
                    "target": "a0",
                    "to": "a0.eng.srt",
                    "language": "eng",
                },
                {
                    "id": "e_es",
                    "at": "2s",
                    "action": "embed_subtitle",
                    "target": "a0",
                    "sidecar_path": "a0.eng.srt",
                },
            ]
        )
        ids = IdAllocator(TraceRecorder())
        state = build_initial_state(scenario, ids)
        resolved_events = list(resolve_timeline(scenario))
        apply_event(state, resolved_events[0], ids, _RUN_ID, scenario.scenario_id)
        prior_version_id = state.version_id_for_asset("a0")
        entries = apply_event(state, resolved_events[1], ids, _RUN_ID, scenario.scenario_id)
        entry = entries[0]
        assert entry.input_version_ids == [prior_version_id]
        assert entry.output_version_ids[0] != prior_version_id

    def test_embed_removes_sidecar_from_state(self) -> None:
        scenario = _scenario_with_subtitle_declared(
            [
                {
                    "id": "e_cs",
                    "at": "1s",
                    "action": "create_sidecar",
                    "target": "a0",
                    "to": "a0.eng.srt",
                    "language": "eng",
                },
                {
                    "id": "e_es",
                    "at": "2s",
                    "action": "embed_subtitle",
                    "target": "a0",
                    "sidecar_path": "a0.eng.srt",
                },
            ]
        )
        ids = IdAllocator(TraceRecorder())
        state = build_initial_state(scenario, ids)
        resolved_events = list(resolve_timeline(scenario))
        apply_event(state, resolved_events[0], ids, _RUN_ID, scenario.scenario_id)
        assert len(state.sidecars) == 1
        apply_event(state, resolved_events[1], ids, _RUN_ID, scenario.scenario_id)
        assert len(state.sidecars) == 0

    def test_embed_state_delta_records_sidecar_id_and_path(self) -> None:
        scenario = _scenario_with_subtitle_declared(
            [
                {
                    "id": "e_cs",
                    "at": "1s",
                    "action": "create_sidecar",
                    "target": "a0",
                    "to": "a0.eng.srt",
                    "language": "eng",
                },
                {
                    "id": "e_es",
                    "at": "2s",
                    "action": "embed_subtitle",
                    "target": "a0",
                    "sidecar_path": "a0.eng.srt",
                },
            ]
        )
        ids = IdAllocator(TraceRecorder())
        state = build_initial_state(scenario, ids)
        resolved_events = list(resolve_timeline(scenario))
        apply_event(state, resolved_events[0], ids, _RUN_ID, scenario.scenario_id)
        sidecar_id = next(iter(state.sidecars.keys()))
        entries = apply_event(state, resolved_events[1], ids, _RUN_ID, scenario.scenario_id)
        delta = entries[0].state_delta
        assert delta["embedded_sidecar_id"] == sidecar_id
        assert delta["embedded_sidecar_path"] == "a0.eng.srt"
        assert delta["language"] == "eng"
        assert delta["kind"] == "subtitle"
        # Match the sibling tests' pattern: assert input/output paths converge.
        assert delta["input_path"] == delta["output_path"]
