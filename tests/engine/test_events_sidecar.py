"""Tests for the 4 sidecar-touching handlers added in Sprint 7.

embed_subtitle, extract_subtitle, remove_sidecar, update_sidecar.

Also covers ``_handle_create_sidecar`` kind routing — Sprint 6 only
emitted subtitle sidecars; Sprint 7 widened ``CreateSidecarEvent.kind``
to include ``poster`` and ``nfo``, and the handler must route on it
(#50).
"""

from __future__ import annotations

import uuid

from chaos_librarian.contract.scenario import Scenario, SidecarKind
from chaos_librarian.determinism import IdAllocator, TraceRecorder
from chaos_librarian.engine.events import apply_event
from chaos_librarian.engine.resolution import resolve_timeline
from chaos_librarian.engine.state import build_initial_state
from tests.engine.conftest import _engine_event_context

_RUN_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")


def _scenario_with_subtitle_declared(timeline: list[dict[str, object]]) -> Scenario:
    """Asset declares one English subtitle as a sidecar next to the media path.

    ``build_initial_state`` seeds one ``ManifestSidecar`` per declared
    sidecar-mode subtitle into ``state.sidecars`` (the fixture below
    yields one row with id ``sidecar_a0_eng``); ``create_sidecar`` for the
    same ``(asset_id, language)`` replaces that row, and the Sprint 7
    handlers (embed/update/remove) resolve the declared row directly.
    """
    return Scenario.model_validate(
        {
            "schema_version": 17,
            "scenario_id": "sidecar_tests",
            "seed": 1,
            "duration_scale": "short",
            "library": {"roots": [{"id": "r0", "path": "library/r0"}]},
            "movies": [
                {
                    "id": "movie_0",
                    "title": "T",
                    "layout": "movie_flat",
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
            "series": [],
            "artists": [],
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
        apply_event(
            state,
            resolved_events[0],
            ids,
            _engine_event_context(scenario.scenario_id, run_id=_RUN_ID),
        )
        prior_version_id = state.version_id_for_asset("a0")
        entries = apply_event(
            state,
            resolved_events[1],
            ids,
            _engine_event_context(scenario.scenario_id, run_id=_RUN_ID),
        )
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
        apply_event(
            state,
            resolved_events[0],
            ids,
            _engine_event_context(scenario.scenario_id, run_id=_RUN_ID),
        )
        assert len(state.sidecars) == 1
        apply_event(
            state,
            resolved_events[1],
            ids,
            _engine_event_context(scenario.scenario_id, run_id=_RUN_ID),
        )
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
        apply_event(
            state,
            resolved_events[0],
            ids,
            _engine_event_context(scenario.scenario_id, run_id=_RUN_ID),
        )
        sidecar_id = next(iter(state.sidecars.keys()))
        entries = apply_event(
            state,
            resolved_events[1],
            ids,
            _engine_event_context(scenario.scenario_id, run_id=_RUN_ID),
        )
        delta = entries[0].state_delta
        assert delta["embedded_sidecar_id"] == sidecar_id
        assert delta["embedded_sidecar_path"] == "a0.eng.srt"
        assert delta["language"] == "eng"
        assert delta["kind"] == "subtitle"
        # Match the sibling tests' pattern: assert input/output paths converge.
        assert delta["input_path"] == delta["output_path"]


class TestExtractSubtitleHandler:
    """extract_subtitle allocates a NEW sidecar but DOES NOT bump the asset's version.

    WHY: extract is read-only on the asset — the bytes don't change.
    The asymmetry with embed_subtitle (which DOES allocate) is correct.
    """

    def test_extract_allocates_new_sidecar(self) -> None:
        scenario = _scenario_with_subtitle_declared(
            [
                {
                    "id": "e_xs",
                    "at": "1s",
                    "action": "extract_subtitle",
                    "target": "a0",
                    "to": "a0.fra.srt",
                    "language": "fra",
                },
            ]
        )
        ids = IdAllocator(TraceRecorder())
        state = build_initial_state(scenario, ids)
        # ``build_initial_state`` seeds one row per declared sidecar-mode
        # subtitle (the asset declares one eng subtitle); extract_subtitle
        # then allocates a second row for the freshly extracted fra track.
        baseline = len(state.sidecars)
        assert baseline == 1
        (resolved,) = resolve_timeline(scenario)
        apply_event(
            state, resolved, ids, _engine_event_context(scenario.scenario_id, run_id=_RUN_ID)
        )
        assert len(state.sidecars) == baseline + 1
        sidecar = next(s for s in state.sidecars.values() if s.language == "fra")
        assert sidecar.kind == SidecarKind.SUBTITLE.value
        assert sidecar.path == "a0.fra.srt"
        assert sidecar.asset_id == "a0"

    def test_extract_does_not_allocate_new_version(self) -> None:
        scenario = _scenario_with_subtitle_declared(
            [
                {
                    "id": "e_xs",
                    "at": "1s",
                    "action": "extract_subtitle",
                    "target": "a0",
                    "to": "a0.fra.srt",
                    "language": "fra",
                },
            ]
        )
        ids = IdAllocator(TraceRecorder())
        state = build_initial_state(scenario, ids)
        prior_version_id = state.version_id_for_asset("a0")
        (resolved,) = resolve_timeline(scenario)
        entries = apply_event(
            state, resolved, ids, _engine_event_context(scenario.scenario_id, run_id=_RUN_ID)
        )
        # Same version after — extract is read-only.
        assert state.version_id_for_asset("a0") == prior_version_id
        # And the journal entry's input/output version ids are EMPTY.
        assert entries[0].input_version_ids == []
        assert entries[0].output_version_ids == []

    def test_extract_state_delta_records_sidecar_and_paths(self) -> None:
        scenario = _scenario_with_subtitle_declared(
            [
                {
                    "id": "e_xs",
                    "at": "1s",
                    "action": "extract_subtitle",
                    "target": "a0",
                    "to": "a0.fra.srt",
                    "language": "fra",
                },
            ]
        )
        ids = IdAllocator(TraceRecorder())
        state = build_initial_state(scenario, ids)
        (resolved,) = resolve_timeline(scenario)
        entries = apply_event(
            state, resolved, ids, _engine_event_context(scenario.scenario_id, run_id=_RUN_ID)
        )
        delta = entries[0].state_delta
        assert delta["sidecar_path"] == "a0.fra.srt"
        assert delta["language"] == "fra"
        input_path = delta["input_path"]
        assert isinstance(input_path, str)
        assert input_path.endswith("/T - hd.mkv")
        # extract has no output_path key — its output IS sidecar_path.
        assert "output_path" not in delta


class TestRemoveSidecarHandler:
    """remove_sidecar removes the sidecar from state; no version change."""

    def test_remove_drops_sidecar(self) -> None:
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
                    "id": "e_rs",
                    "at": "2s",
                    "action": "remove_sidecar",
                    "target": "a0",
                    "sidecar_path": "a0.eng.srt",
                },
            ]
        )
        ids = IdAllocator(TraceRecorder())
        state = build_initial_state(scenario, ids)
        resolved_events = list(resolve_timeline(scenario))
        apply_event(
            state,
            resolved_events[0],
            ids,
            _engine_event_context(scenario.scenario_id, run_id=_RUN_ID),
        )
        assert len(state.sidecars) == 1
        apply_event(
            state,
            resolved_events[1],
            ids,
            _engine_event_context(scenario.scenario_id, run_id=_RUN_ID),
        )
        assert len(state.sidecars) == 0

    def test_remove_state_delta_records_id_and_path(self) -> None:
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
                    "id": "e_rs",
                    "at": "2s",
                    "action": "remove_sidecar",
                    "target": "a0",
                    "sidecar_path": "a0.eng.srt",
                },
            ]
        )
        ids = IdAllocator(TraceRecorder())
        state = build_initial_state(scenario, ids)
        resolved_events = list(resolve_timeline(scenario))
        apply_event(
            state,
            resolved_events[0],
            ids,
            _engine_event_context(scenario.scenario_id, run_id=_RUN_ID),
        )
        sidecar_id = next(iter(state.sidecars.keys()))
        entries = apply_event(
            state,
            resolved_events[1],
            ids,
            _engine_event_context(scenario.scenario_id, run_id=_RUN_ID),
        )
        delta = entries[0].state_delta
        assert delta["removed_sidecar_id"] == sidecar_id
        assert delta["removed_sidecar_path"] == "a0.eng.srt"

    def test_remove_does_not_allocate_version(self) -> None:
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
                    "id": "e_rs",
                    "at": "2s",
                    "action": "remove_sidecar",
                    "target": "a0",
                    "sidecar_path": "a0.eng.srt",
                },
            ]
        )
        ids = IdAllocator(TraceRecorder())
        state = build_initial_state(scenario, ids)
        resolved_events = list(resolve_timeline(scenario))
        apply_event(
            state,
            resolved_events[0],
            ids,
            _engine_event_context(scenario.scenario_id, run_id=_RUN_ID),
        )
        prior_version_id = state.version_id_for_asset("a0")
        apply_event(
            state,
            resolved_events[1],
            ids,
            _engine_event_context(scenario.scenario_id, run_id=_RUN_ID),
        )
        assert state.version_id_for_asset("a0") == prior_version_id


class TestUpdateSidecarHandler:
    """update_sidecar emits a journal entry but does NO state mutation.

    WHY: the actual content_hash change happens in phase B (the
    materializer regenerates bytes with a perturbed sub-seed). Plan-only
    mode has no way to mark the sidecar as "updated", and that's
    accepted — plan-only is bytes-blind.
    """

    def test_update_does_not_mutate_state(self) -> None:
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
                    "id": "e_us",
                    "at": "2s",
                    "action": "update_sidecar",
                    "target": "a0",
                    "sidecar_path": "a0.eng.srt",
                },
            ]
        )
        ids = IdAllocator(TraceRecorder())
        state = build_initial_state(scenario, ids)
        resolved_events = list(resolve_timeline(scenario))
        apply_event(
            state,
            resolved_events[0],
            ids,
            _engine_event_context(scenario.scenario_id, run_id=_RUN_ID),
        )
        sidecars_before = dict(state.sidecars)
        apply_event(
            state,
            resolved_events[1],
            ids,
            _engine_event_context(scenario.scenario_id, run_id=_RUN_ID),
        )
        # Same dict; same sidecar_ids; same fields.
        assert state.sidecars.keys() == sidecars_before.keys()

    def test_update_state_delta_records_sidecar_id_and_path(self) -> None:
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
                    "id": "e_us",
                    "at": "2s",
                    "action": "update_sidecar",
                    "target": "a0",
                    "sidecar_path": "a0.eng.srt",
                },
            ]
        )
        ids = IdAllocator(TraceRecorder())
        state = build_initial_state(scenario, ids)
        resolved_events = list(resolve_timeline(scenario))
        apply_event(
            state,
            resolved_events[0],
            ids,
            _engine_event_context(scenario.scenario_id, run_id=_RUN_ID),
        )
        sidecar_id = next(iter(state.sidecars.keys()))
        entries = apply_event(
            state,
            resolved_events[1],
            ids,
            _engine_event_context(scenario.scenario_id, run_id=_RUN_ID),
        )
        delta = entries[0].state_delta
        assert delta["sidecar_id"] == sidecar_id
        assert delta["sidecar_path"] == "a0.eng.srt"


class TestCreateSidecarKindRouting:
    """create_sidecar must route on event.kind for poster/NFO (#50).

    WHY: Sprint 7 widened ``CreateSidecarEvent.kind`` to include
    ``poster`` and ``nfo``. The engine previously hardcoded
    ``kind="subtitle"`` on every emitted ``ManifestSidecar`` row,
    silently mislabelling poster/NFO sidecars. The handler must use
    ``event.kind.value`` so manifest rows carry the kind the scenario
    declared.
    """

    def _scenario_with_one_asset(self, timeline: list[dict[str, object]]) -> Scenario:
        """Asset declares NO subtitle — keeps the seeded sidecars list empty.

        Lets each poster/NFO test assert ``state.sidecars`` size precisely
        without filtering out a baseline declared subtitle row.
        """
        return Scenario.model_validate(
            {
                "schema_version": 17,
                "scenario_id": "create_sidecar_kind",
                "seed": 1,
                "duration_scale": "short",
                "library": {"roots": [{"id": "r0", "path": "library/r0"}]},
                "movies": [
                    {
                        "id": "movie_0",
                        "title": "T",
                        "layout": "movie_flat",
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
        )

    def test_poster_sidecar_carries_kind_and_no_language(self) -> None:
        scenario = self._scenario_with_one_asset(
            [
                {
                    "id": "ev_poster",
                    "at": "0s",
                    "action": "create_sidecar",
                    "target": "a0",
                    "to": "library/r0/a0.poster.png",
                    "kind": "poster",
                }
            ]
        )
        ids = IdAllocator(TraceRecorder())
        state = build_initial_state(scenario, ids)
        prior_version_id = state.version_id_for_asset("a0")
        (resolved,) = resolve_timeline(scenario)
        entries = apply_event(
            state, resolved, ids, _engine_event_context(scenario.scenario_id, run_id=_RUN_ID)
        )
        # One new sidecar row, labeled poster, with no language.
        assert len(state.sidecars) == 1
        sidecar = next(iter(state.sidecars.values()))
        assert sidecar.kind == SidecarKind.POSTER.value
        assert sidecar.path == "library/r0/a0.poster.png"
        assert sidecar.language is None
        assert sidecar.asset_id == "a0"
        # No version bump.
        assert state.version_id_for_asset("a0") == prior_version_id
        # Journal shape mirrors the subtitle branch (atomic atomic atomic).
        entry = entries[0]
        assert entry.action == "create_sidecar"
        assert entry.target_ids == ["a0"]
        assert entry.input_version_ids == []
        assert entry.output_version_ids == []
        delta = entry.state_delta
        assert delta["sidecar_path"] == "library/r0/a0.poster.png"
        assert delta["sidecar_id"] == sidecar.id
        assert delta["language"] is None

    def test_nfo_sidecar_carries_kind_and_no_language(self) -> None:
        scenario = self._scenario_with_one_asset(
            [
                {
                    "id": "ev_nfo",
                    "at": "0s",
                    "action": "create_sidecar",
                    "target": "a0",
                    "to": "library/r0/a0.nfo",
                    "kind": "nfo",
                }
            ]
        )
        ids = IdAllocator(TraceRecorder())
        state = build_initial_state(scenario, ids)
        prior_version_id = state.version_id_for_asset("a0")
        (resolved,) = resolve_timeline(scenario)
        entries = apply_event(
            state, resolved, ids, _engine_event_context(scenario.scenario_id, run_id=_RUN_ID)
        )
        assert len(state.sidecars) == 1
        sidecar = next(iter(state.sidecars.values()))
        assert sidecar.kind == SidecarKind.NFO.value
        assert sidecar.path == "library/r0/a0.nfo"
        assert sidecar.language is None
        # No version bump.
        assert state.version_id_for_asset("a0") == prior_version_id
        entry = entries[0]
        assert entry.action == "create_sidecar"
        delta = entry.state_delta
        assert delta["sidecar_path"] == "library/r0/a0.nfo"
        assert delta["sidecar_id"] == sidecar.id
        assert delta["language"] is None

    def test_subtitle_default_kind_still_dedups_declared_row(self) -> None:
        """Regression guard: subtitle branch behavior preserved after refactor.

        ``build_initial_state`` seeds one declared subtitle row; a
        same-language ``create_sidecar`` must replace (not duplicate) it.
        """
        scenario = _scenario_with_subtitle_declared(
            [
                {
                    "id": "e_cs",
                    "at": "1s",
                    "action": "create_sidecar",
                    "target": "a0",
                    "to": "a0.eng.srt",
                    "language": "eng",
                }
            ]
        )
        ids = IdAllocator(TraceRecorder())
        state = build_initial_state(scenario, ids)
        assert len(state.sidecars) == 1  # declared row from build_initial_state
        (resolved,) = resolve_timeline(scenario)
        apply_event(
            state, resolved, ids, _engine_event_context(scenario.scenario_id, run_id=_RUN_ID)
        )
        # Still one row — the declared row was replaced, not duplicated.
        assert len(state.sidecars) == 1
        sidecar = next(iter(state.sidecars.values()))
        assert sidecar.kind == SidecarKind.SUBTITLE.value
        assert sidecar.language == "eng"
