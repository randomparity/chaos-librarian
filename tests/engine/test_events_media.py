"""Tests for media + sidecar handlers in chaos_librarian.engine.events."""

from __future__ import annotations

import uuid

import pytest

from chaos_librarian.contract.journal import AtomicJournalEntry, JournalPhase
from chaos_librarian.contract.scenario import Scenario
from chaos_librarian.determinism import IdAllocator, TraceRecorder
from chaos_librarian.engine.events import apply_event
from chaos_librarian.engine.resolution import resolve_timeline
from chaos_librarian.engine.state import build_initial_state

_RUN_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")


def _scenario(timeline: list[dict[str, object]]) -> Scenario:
    return Scenario.model_validate(
        {
            "schema_version": 4,
            "scenario_id": "media",
            "seed": 1,
            "duration_scale": "short",
            "library": {"roots": [{"id": "r0", "path": "movies-hd"}]},
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
                                            "resolution": "1080p",
                                        },
                                        "audio": [
                                            {
                                                "codec": "aac",
                                                "channels": "5.1",
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
            "timeline": timeline,
        }
    )


class TestReencodeVideoHandler:
    """reencode_video allocates a new version and records the codec/resolution delta.

    WHY: version history is the oracle for "the file's content changed";
    voom-v2's reconciliation depends on it.
    """

    def test_reencode_video_bumps_version(self) -> None:
        scenario = _scenario(
            [
                {
                    "id": "e0",
                    "at": "3s",
                    "action": "reencode_video",
                    "target": "a0",
                    "resolution": "sd",
                    "codec": "h264",
                }
            ]
        )
        ids = IdAllocator(TraceRecorder())
        state = build_initial_state(scenario, ids)
        before_versions = set(state.versions.keys())
        (resolved,) = resolve_timeline(scenario)
        (entry,) = apply_event(state, resolved, ids, _RUN_ID, "media")
        assert isinstance(entry, AtomicJournalEntry)
        assert entry.phase == JournalPhase.ATOMIC
        assert entry.action == "reencode_video"
        new_versions = set(state.versions.keys()) - before_versions
        assert len(new_versions) == 1
        assert entry.state_delta["resolution"] == "sd"
        assert entry.state_delta["codec"] == "h264"


class TestReencodeAudioHandler:
    """reencode_audio bumps version and records channel transition.

    WHY: stereo/5.1 downmix tests rely on the from→to channel delta being
    in the journal — adapters can assert it without re-deriving from probes.
    """

    def test_reencode_audio_records_channel_transition(self) -> None:
        scenario = _scenario(
            [
                {
                    "id": "e0",
                    "at": "3s",
                    "action": "reencode_audio",
                    "target": "a0",
                    "from_channels": "5.1",
                    "to_channels": "stereo",
                }
            ]
        )
        ids = IdAllocator(TraceRecorder())
        state = build_initial_state(scenario, ids)
        (resolved,) = resolve_timeline(scenario)
        (entry,) = apply_event(state, resolved, ids, _RUN_ID, "media")
        assert entry.action == "reencode_audio"
        assert entry.state_delta["from_channels"] == "5.1"
        assert entry.state_delta["to_channels"] == "stereo"


class TestCreateSidecarHandler:
    """create_sidecar allocates a new sidecar id and records the path.

    WHY: sidecar reconciliation tests (Bundle Sidecars first-pack
    scenario) need a deterministic sidecar id and a reference to the
    asset it belongs to.
    """

    def test_create_sidecar_emits_sidecar_id(self) -> None:
        scenario = _scenario(
            [
                {
                    "id": "e0",
                    "at": "1s",
                    "action": "create_sidecar",
                    "target": "a0",
                    "to": "movies-hd/a0.eng.srt",
                    "language": "eng",
                }
            ]
        )
        ids = IdAllocator(TraceRecorder())
        state = build_initial_state(scenario, ids)
        (resolved,) = resolve_timeline(scenario)
        (entry,) = apply_event(state, resolved, ids, _RUN_ID, "media")
        assert entry.action == "create_sidecar"
        assert entry.state_delta["sidecar_path"] == "movies-hd/a0.eng.srt"
        assert len(state.sidecars) == 1
        (sidecar,) = state.sidecars.values()
        assert sidecar.asset_id == "a0"
        assert sidecar.path == "movies-hd/a0.eng.srt"
        assert sidecar.language == "eng"


class TestReencodeAudioOnUnplacedAssetCrashes:
    """Engine crashes if reencode_audio runs on an asset with no location.

    WHY: encodes the necessity of the E_LIFECYCLE_INVALID rule that flags
    ``reencode_audio`` on an unplaced asset. If this regression starts
    passing (i.e. no KeyError) the engine has gained a defensive branch
    that may make the validation rule redundant — at which point the rule
    and this test need a coordinated re-evaluation.
    """

    def test_reencode_audio_after_delete_raises_keyerror(self) -> None:
        scenario = _scenario(
            [
                {"id": "e1", "at": "0", "action": "delete_file", "target": "a0"},
            ]
        )
        ids = IdAllocator(TraceRecorder())
        state = build_initial_state(scenario, ids)
        (delete_resolved,) = resolve_timeline(scenario)
        apply_event(state, delete_resolved, ids, _RUN_ID, "media")
        assert not state.has_location("a0")

        bad_scenario = _scenario(
            [
                {
                    "id": "e2",
                    "at": "1s",
                    "action": "reencode_audio",
                    "target": "a0",
                    "from_channels": "5.1",
                    "to_channels": "stereo",
                }
            ]
        )
        (reencode_resolved,) = resolve_timeline(bad_scenario)
        with pytest.raises(KeyError):
            apply_event(state, reencode_resolved, ids, _RUN_ID, "media")
