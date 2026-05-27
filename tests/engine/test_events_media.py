"""Tests for media + sidecar handlers in chaos_librarian.engine.events."""

from __future__ import annotations

import uuid

import pytest

from chaos_librarian.contract.journal import AtomicJournalEntry, JournalPhase
from chaos_librarian.contract.profiles import ProfileName
from chaos_librarian.contract.scenario import Scenario
from chaos_librarian.determinism import IdAllocator, TraceRecorder
from chaos_librarian.engine.events import _swap_extension, apply_event
from chaos_librarian.engine.resolution import resolve_timeline
from chaos_librarian.engine.state import build_initial_state
from tests.engine.conftest import _engine_event_context

_RUN_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")


def _scenario(
    timeline: list[dict[str, object]],
    *,
    profiles: list[str] | None = None,
) -> Scenario:
    payload: dict[str, object] = {
        "schema_version": 22,
        "scenario_id": "media",
        "seed": 1,
        "duration_scale": "short",
        "library": {"roots": [{"id": "r0", "path": "movies-hd"}]},
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
        "series": [],
        "artists": [],
        "timeline": timeline,
    }
    if profiles is not None:
        payload["profiles"] = profiles
    return Scenario.model_validate(payload)


class TestCorruptContainerHeaderHandler:
    """corrupt_container_header allocates a deterministic corruption version."""

    def test_corrupt_container_header_allocates_new_version_and_keeps_path(self) -> None:
        scenario = _scenario(
            [
                {
                    "id": "corrupt_header_001",
                    "at": "1s",
                    "action": "corrupt_container_header",
                    "target": "a0",
                }
            ],
            profiles=["malformed-media"],
        )
        ids = IdAllocator(TraceRecorder())
        state = build_initial_state(scenario, ids)
        original_path = state.locations[state.location_id_for_asset("a0")].path
        prior_version_id = state.version_id_for_asset("a0")
        (resolved,) = resolve_timeline(scenario)

        (entry,) = apply_event(
            state,
            resolved,
            ids,
            _engine_event_context("media", run_id=_RUN_ID, resolved_seed=42),
        )

        new_version_id = state.version_id_for_asset("a0")
        assert new_version_id != prior_version_id
        assert state.locations[state.location_id_for_asset("a0")].path == original_path
        assert entry.input_version_ids == [prior_version_id]
        assert entry.output_version_ids == [new_version_id]

    def test_corrupt_container_header_journal_records_corruption_metadata(self) -> None:
        scenario = _scenario(
            [
                {
                    "id": "corrupt_header_001",
                    "at": "1s",
                    "action": "corrupt_container_header",
                    "target": "a0",
                    "bytes": 128,
                }
            ],
            profiles=["malformed-media"],
        )
        ids = IdAllocator(TraceRecorder())
        state = build_initial_state(scenario, ids)
        (resolved,) = resolve_timeline(scenario)

        (entry,) = apply_event(
            state,
            resolved,
            ids,
            _engine_event_context("media", run_id=_RUN_ID, resolved_seed=42),
        )

        assert entry.state_delta == {
            "input_path": "movies-hd/T - hd.mkv",
            "output_path": "movies-hd/T - hd.mkv",
            "profile": ProfileName.MALFORMED_MEDIA.value,
            "corruptor": "container_header_v1",
            "byte_start": 0,
            "byte_count": 128,
            "seed_material": "container_header_v1:42:corrupt_header_001:a0",
        }
        version = state.versions[entry.output_version_ids[0]]
        assert version.corruption is not None
        assert version.corruption.model_dump(mode="json") == {
            "profile": "malformed-media",
            "event_id": "corrupt_header_001",
            "corruptor": "container_header_v1",
            "byte_start": 0,
            "byte_count": 128,
            "seed_material": "container_header_v1:42:corrupt_header_001:a0",
            "stream": None,
            "packet_start": None,
            "packet_count": None,
            "metadata": {},
        }

    def test_corrupt_container_header_uses_resolved_seed_in_seed_material(self) -> None:
        scenario = _scenario(
            [
                {
                    "id": "corrupt_header_001",
                    "at": "1s",
                    "action": "corrupt_container_header",
                    "target": "a0",
                }
            ],
            profiles=["malformed-media"],
        )
        ids = IdAllocator(TraceRecorder())
        state = build_initial_state(scenario, ids)
        (resolved,) = resolve_timeline(scenario)

        (entry,) = apply_event(
            state,
            resolved,
            ids,
            _engine_event_context("media", run_id=_RUN_ID, resolved_seed=777),
        )

        assert entry.state_delta["seed_material"] == "container_header_v1:777:corrupt_header_001:a0"


class TestInterceptorHandlers:
    """Interceptors emit deterministic journal evidence for phase-B materializers."""

    @pytest.mark.parametrize(
        ("event", "expected_delta", "expected_corruptor"),
        [
            (
                {
                    "id": "truncate_001",
                    "at": "1s",
                    "action": "truncate_file",
                    "target": "a0",
                    "keep_bytes": 64,
                },
                {
                    "input_path": "movies-hd/T - hd.mkv",
                    "output_path": "movies-hd/T - hd.mkv",
                    "profile": "malformed-media",
                    "corruptor": "truncate_file_v1",
                    "keep_bytes": 64,
                    "seed_material": "truncate_file_v1:42:truncate_001:a0",
                },
                "truncate_file_v1",
            ),
            (
                {
                    "id": "packet_corrupt_001",
                    "at": "1s",
                    "action": "corrupt_packet_range",
                    "target": "a0",
                    "stream": "video",
                    "packet_start": 0,
                    "packet_count": 2,
                },
                {
                    "input_path": "movies-hd/T - hd.mkv",
                    "output_path": "movies-hd/T - hd.mkv",
                    "profile": "malformed-media",
                    "corruptor": "packet_range_v1",
                    "stream": "video",
                    "packet_start": 0,
                    "packet_count": 2,
                    "seed_material": "packet_range_v1:42:packet_corrupt_001:a0",
                },
                "packet_range_v1",
            ),
            (
                {
                    "id": "duration_bad_001",
                    "at": "1s",
                    "action": "write_invalid_duration_metadata",
                    "target": "a0",
                    "value": "not-a-duration",
                },
                {
                    "input_path": "movies-hd/T - hd.mkv",
                    "output_path": "movies-hd/T - hd.mkv",
                    "profile": "malformed-media",
                    "corruptor": "invalid_duration_metadata_v1",
                    "value": "not-a-duration",
                    "seed_material": "invalid_duration_metadata_v1:42:duration_bad_001:a0",
                },
                "invalid_duration_metadata_v1",
            ),
        ],
    )
    def test_malformed_media_interceptors_allocate_corruption_versions(
        self,
        event: dict[str, object],
        expected_delta: dict[str, object],
        expected_corruptor: str,
    ) -> None:
        scenario = _scenario([event], profiles=["malformed-media"])
        ids = IdAllocator(TraceRecorder())
        state = build_initial_state(scenario, ids)
        prior_version_id = state.version_id_for_asset("a0")
        (resolved,) = resolve_timeline(scenario)

        (entry,) = apply_event(
            state,
            resolved,
            ids,
            _engine_event_context("media", run_id=_RUN_ID, resolved_seed=42),
        )

        new_version_id = state.version_id_for_asset("a0")
        assert isinstance(entry, AtomicJournalEntry)
        assert entry.phase == JournalPhase.ATOMIC
        assert entry.state_delta == expected_delta
        assert entry.input_version_ids == [prior_version_id]
        assert entry.output_version_ids == [new_version_id]
        assert new_version_id != prior_version_id
        version = state.versions[new_version_id]
        assert version.corruption is not None
        assert version.corruption.corruptor == expected_corruptor

    def test_touch_mtime_records_filesystem_delta_without_new_version(self) -> None:
        scenario = _scenario(
            [
                {
                    "id": "touch_mtime_001",
                    "at": "1s",
                    "action": "touch_mtime",
                    "target": "a0",
                    "offset": "2s",
                }
            ],
            profiles=["filesystem-artifacts"],
        )
        ids = IdAllocator(TraceRecorder())
        state = build_initial_state(scenario, ids)
        prior_version_id = state.version_id_for_asset("a0")
        (resolved,) = resolve_timeline(scenario)

        (entry,) = apply_event(
            state,
            resolved,
            ids,
            _engine_event_context("media", run_id=_RUN_ID, resolved_seed=42),
        )

        assert isinstance(entry, AtomicJournalEntry)
        assert entry.phase == JournalPhase.ATOMIC
        assert entry.state_delta == {
            "path": "movies-hd/T - hd.mkv",
            "profile": "filesystem-artifacts",
            "offset": "2s",
        }
        assert entry.input_version_ids == []
        assert entry.output_version_ids == []
        assert state.version_id_for_asset("a0") == prior_version_id

    def test_wrong_oracle_hash_allocates_uncorrupted_version(self) -> None:
        scenario = _scenario(
            [
                {
                    "id": "wrong_hash_001",
                    "at": "1s",
                    "action": "wrong_oracle_hash",
                    "target": "a0",
                }
            ],
            profiles=["negative-oracle"],
        )
        ids = IdAllocator(TraceRecorder())
        state = build_initial_state(scenario, ids)
        prior_version_id = state.version_id_for_asset("a0")
        (resolved,) = resolve_timeline(scenario)

        (entry,) = apply_event(
            state,
            resolved,
            ids,
            _engine_event_context("media", run_id=_RUN_ID, resolved_seed=42),
        )

        new_version_id = state.version_id_for_asset("a0")
        assert isinstance(entry, AtomicJournalEntry)
        assert entry.phase == JournalPhase.ATOMIC
        assert entry.state_delta == {
            "input_path": "movies-hd/T - hd.mkv",
            "output_path": "movies-hd/T - hd.mkv",
            "profile": "negative-oracle",
            "algorithm": "sha256",
            "seed_material": "wrong_oracle_hash_v1:42:wrong_hash_001:a0",
        }
        assert entry.input_version_ids == [prior_version_id]
        assert entry.output_version_ids == [new_version_id]
        assert new_version_id != prior_version_id
        assert state.versions[new_version_id].corruption is None


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
        (entry,) = apply_event(state, resolved, ids, _engine_event_context("media", run_id=_RUN_ID))
        assert isinstance(entry, AtomicJournalEntry)
        assert entry.phase == JournalPhase.ATOMIC
        assert entry.action == "reencode_video"
        new_versions = set(state.versions.keys()) - before_versions
        assert len(new_versions) == 1
        assert entry.state_delta["resolution"] == "sd"
        assert entry.state_delta["codec"] == "h264"

    def test_reencode_video_emits_input_and_output_path(self) -> None:
        scenario = _scenario(
            [
                {
                    "id": "e0",
                    "at": "1s",
                    "action": "reencode_video",
                    "target": "a0",
                    "resolution": "sd",
                    "codec": "h264",
                }
            ]
        )
        ids = IdAllocator(TraceRecorder())
        state = build_initial_state(scenario, ids)
        (resolved,) = resolve_timeline(scenario)
        (entry,) = apply_event(state, resolved, ids, _engine_event_context("media", run_id=_RUN_ID))
        assert isinstance(entry, AtomicJournalEntry)
        input_path = entry.state_delta["input_path"]
        output_path = entry.state_delta["output_path"]
        assert isinstance(input_path, str)
        assert isinstance(output_path, str)
        # In-place re-encode: input and output paths are identical.
        assert input_path == output_path
        assert input_path.endswith("/T - hd.mkv")


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
        (entry,) = apply_event(state, resolved, ids, _engine_event_context("media", run_id=_RUN_ID))
        assert entry.action == "reencode_audio"
        assert entry.state_delta["from_channels"] == "5.1"
        assert entry.state_delta["to_channels"] == "stereo"

    def test_reencode_audio_emits_input_and_output_path(self) -> None:
        scenario = _scenario(
            [
                {
                    "id": "e0",
                    "at": "1s",
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
        (entry,) = apply_event(state, resolved, ids, _engine_event_context("media", run_id=_RUN_ID))
        assert isinstance(entry, AtomicJournalEntry)
        input_path = entry.state_delta["input_path"]
        output_path = entry.state_delta["output_path"]
        assert isinstance(input_path, str)
        assert isinstance(output_path, str)
        assert input_path == output_path
        assert input_path.endswith("/T - hd.mkv")


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
        (entry,) = apply_event(state, resolved, ids, _engine_event_context("media", run_id=_RUN_ID))
        assert entry.action == "create_sidecar"
        assert entry.state_delta == {
            "sidecar_path": "movies-hd/a0.eng.srt",
            "sidecar_id": "sidecar_0001",
            "language": "eng",
            "kind": "subtitle",
        }
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
        apply_event(state, delete_resolved, ids, _engine_event_context("media", run_id=_RUN_ID))
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
            apply_event(
                state, reencode_resolved, ids, _engine_event_context("media", run_id=_RUN_ID)
            )


class TestRemuxContainerHandler:
    """remux_container allocates a new version and rewrites the location path's extension.

    WHY: container changes are observable bytes-affecting changes (codec
    copy is fine, but the wrapper differs); voom-v2's reconciliation
    treats this as a new version.
    """

    def test_remux_allocates_new_version(self) -> None:
        scenario = _scenario(
            [
                {
                    "id": "e0",
                    "at": "1s",
                    "action": "remux_container",
                    "target": "a0",
                    "to_container": "mp4",
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
        entry = entries[0]
        assert isinstance(entry, AtomicJournalEntry)
        assert entry.input_version_ids == [prior_version_id]
        new_version_id = entry.output_version_ids[0]
        assert new_version_id != prior_version_id
        assert state.versions[new_version_id].index == 1

    def test_remux_rewrites_path_extension(self) -> None:
        scenario = _scenario(
            [
                {
                    "id": "e0",
                    "at": "1s",
                    "action": "remux_container",
                    "target": "a0",
                    "to_container": "mp4",
                }
            ]
        )
        ids = IdAllocator(TraceRecorder())
        state = build_initial_state(scenario, ids)
        loc_id = state.location_id_for_asset("a0")
        old_path = state.locations[loc_id].path
        assert old_path.endswith(".mkv")
        (resolved,) = resolve_timeline(scenario)
        apply_event(
            state, resolved, ids, _engine_event_context(scenario.scenario_id, run_id=_RUN_ID)
        )
        new_path = state.locations[loc_id].path
        assert new_path == old_path[:-4] + ".mp4"

    def test_remux_state_delta_records_paths_and_containers(self) -> None:
        scenario = _scenario(
            [
                {
                    "id": "e0",
                    "at": "1s",
                    "action": "remux_container",
                    "target": "a0",
                    "to_container": "mp4",
                }
            ]
        )
        ids = IdAllocator(TraceRecorder())
        state = build_initial_state(scenario, ids)
        (resolved,) = resolve_timeline(scenario)
        entries = apply_event(
            state, resolved, ids, _engine_event_context(scenario.scenario_id, run_id=_RUN_ID)
        )
        delta = entries[0].state_delta
        from_container = delta["from_container"]
        to_container = delta["to_container"]
        from_path = delta["from_path"]
        to_path = delta["to_path"]
        input_path = delta["input_path"]
        output_path = delta["output_path"]
        assert isinstance(from_container, str)
        assert isinstance(to_container, str)
        assert isinstance(from_path, str)
        assert isinstance(to_path, str)
        assert isinstance(input_path, str)
        assert isinstance(output_path, str)
        assert from_container == "mkv"
        assert to_container == "mp4"
        assert from_path.endswith(".mkv")
        assert to_path.endswith(".mp4")
        assert input_path == from_path
        assert output_path == to_path

    def test_remux_from_container_ignores_dots_in_directory_names(self) -> None:
        scenario = _scenario(
            [
                {
                    "id": "e0",
                    "at": "1s",
                    "action": "remux_container",
                    "target": "a0",
                    "to_container": "mp4",
                }
            ]
        )
        ids = IdAllocator(TraceRecorder())
        state = build_initial_state(scenario, ids)
        loc_id = state.location_id_for_asset("a0")
        state.locations[loc_id] = state.locations[loc_id].model_copy(
            update={"path": "movies.with.dot/a0"}
        )
        (resolved,) = resolve_timeline(scenario)

        (entry,) = apply_event(
            state, resolved, ids, _engine_event_context(scenario.scenario_id, run_id=_RUN_ID)
        )

        assert entry.state_delta["from_container"] == ""
        assert entry.state_delta["to_path"] == "movies.with.dot/a0.mp4"


@pytest.mark.parametrize(
    ("path", "new_ext", "expected"),
    [
        ("library/movies-hd/x.mkv", "mp4", "library/movies-hd/x.mp4"),
        ("file", "mp4", "file.mp4"),
        ("foo.bar.mkv", "mp4", "foo.bar.mp4"),
        ("/dir.with.dot/file", "mp4", "/dir.with.dot/file.mp4"),
    ],
)
def test_swap_extension_uses_basename_only(path: str, new_ext: str, expected: str) -> None:
    assert _swap_extension(path, new_ext) == expected


class TestEditMetadataHandler:
    """edit_metadata allocates a new version and copies the fields dict into state_delta.

    WHY: metadata changes don't move bytes around but they DO change the
    asset's identity (the ffprobe output differs); voom-v2 treats them
    as a new version.
    """

    def test_edit_metadata_allocates_version(self) -> None:
        scenario = _scenario(
            [
                {
                    "id": "e0",
                    "at": "1s",
                    "action": "edit_metadata",
                    "target": "a0",
                    "fields": {"title": "X", "year": "2026"},
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
        entry = entries[0]
        assert entry.input_version_ids == [prior_version_id]
        new_version_id = entry.output_version_ids[0]
        assert new_version_id != prior_version_id

    def test_edit_metadata_records_fields(self) -> None:
        scenario = _scenario(
            [
                {
                    "id": "e0",
                    "at": "1s",
                    "action": "edit_metadata",
                    "target": "a0",
                    "fields": {"title": "Pulsar", "year": "2026"},
                }
            ]
        )
        ids = IdAllocator(TraceRecorder())
        state = build_initial_state(scenario, ids)
        (resolved,) = resolve_timeline(scenario)
        entries = apply_event(
            state, resolved, ids, _engine_event_context(scenario.scenario_id, run_id=_RUN_ID)
        )
        delta = entries[0].state_delta
        fields = delta["fields"]
        assert isinstance(fields, dict)
        assert fields == {"title": "Pulsar", "year": "2026"}
        input_path = delta["input_path"]
        output_path = delta["output_path"]
        assert input_path == output_path

    def test_edit_metadata_does_not_change_path(self) -> None:
        scenario = _scenario(
            [
                {
                    "id": "e0",
                    "at": "1s",
                    "action": "edit_metadata",
                    "target": "a0",
                    "fields": {"k": "v"},
                }
            ]
        )
        ids = IdAllocator(TraceRecorder())
        state = build_initial_state(scenario, ids)
        loc_id = state.location_id_for_asset("a0")
        old_path = state.locations[loc_id].path
        (resolved,) = resolve_timeline(scenario)
        apply_event(
            state, resolved, ids, _engine_event_context(scenario.scenario_id, run_id=_RUN_ID)
        )
        assert state.locations[loc_id].path == old_path
