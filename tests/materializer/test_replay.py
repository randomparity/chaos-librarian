"""Run replay materializer tests for Sprint 10 corruption evidence."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

from chaos_librarian.contract import CAPABILITIES_SCHEMA_VERSION, REPLAY_BUNDLE_SCHEMA_VERSION
from chaos_librarian.contract.capabilities import Capabilities, ReadyFor, ToolStatus
from chaos_librarian.contract.content_sources import (
    CacheDisposition,
    ContentSourceCapabilities,
    ContentSourceEvidence,
    ContentTrackKind,
)
from chaos_librarian.contract.journal import JournalEntry
from chaos_librarian.contract.manifest import ProbedMedia, ProbedStream, StreamKind
from chaos_librarian.contract.materialization import (
    CorruptionAction,
    FailureStage,
    MaterializedAsset,
    OracleHashAction,
    Outcome,
    ToolchainInfo,
    ToolInvocation,
)
from chaos_librarian.contract.profiles import CorruptionProbeOutcome
from chaos_librarian.contract.replay_bundle import ExecutionMode, MaterializeReplayBundle
from chaos_librarian.contract.scenario import TimelineActionName
from chaos_librarian.engine import (
    ReplayIntegrityError,
)
from chaos_librarian.engine.journal_io import serialize_journal_bytes
from chaos_librarian.engine.plan import PlanExecutionRequest, run_materializer_plan
from chaos_librarian.materializer import preparation as prep_mod
from chaos_librarian.materializer import replay as replay_mod
from chaos_librarian.materializer.content.synthesis import MaterializeAssetResult
from chaos_librarian.materializer.errors import CapabilityGateError, CorruptionActionError
from chaos_librarian.materializer.phase_b import dispatch as dispatch_mod
from chaos_librarian.materializer.replay import replay_run_bundle
from chaos_librarian.validation import prepare_run_input_from_bytes, run_validation
from tests.materializer.audio_recipe_helpers import AUDIO_NOISE_SCENARIO_BYTES

_RUN_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
_CORRUPTED_HASH = "sha256:" + "2" * 64
_INPUT_HASH = "sha256:" + "1" * 64
_FAKE_PROVIDER = "fake-content-source"
_FAKE_RECIPE_DIGEST = "sha256:" + "f" * 64

_RESOLUTION_SWITCH_SCENARIO = b"""\
schema_version: 32
scenario_id: run-replay-resolution-switch-capability-test
seed: 133
duration_scale: short
library:
  roots:
    - id: movies_hd
      path: movies-hd
movies:
  - id: movie_switch
    title: Resolution Switch
    layout: movie_flat
    variants:
      - id: variant_switch
        label: sd-to-hd
        bundle:
          id: bundle_switch
          assets:
            - id: asset_main
              role: main
              container: ts
              duration_seconds: 1.0
              video:
                source: color_bars
                codec: h264
                resolution: sd
                resolution_sequence: sd_to_hd
series: []
artists: []
timeline: []
"""

_MKV_MUXING_PROFILE_SCENARIO = b"""\
schema_version: 32
scenario_id: run-replay-muxing-profile-capability-test
seed: 138
duration_scale: short
library:
  roots:
    - id: movies_hd
      path: movies-hd
movies:
  - id: movie_mux
    title: Replay Mux Profile
    layout: movie_flat
    variants:
      - id: variant_mux
        label: mkv
        bundle:
          id: bundle_mux
          assets:
            - id: asset_mux
              role: main
              container: mkv
              duration_seconds: 1.0
              matroska_muxing_profile: dense_cues
              video:
                source: color_bars
                codec: h264
                resolution: sd
              audio:
                - source: sine
                  codec: aac
                  channels: stereo
                  language: eng
series: []
artists: []
timeline: []
"""

_WEBM_PROFILE_SCENARIO = b"""\
schema_version: 32
scenario_id: run-replay-webm-capability-test
seed: 138
duration_scale: short
library:
  roots:
    - id: movies_hd
      path: movies-hd
movies:
  - id: movie_webm
    title: Replay WebM Profile
    layout: movie_flat
    variants:
      - id: variant_webm
        label: webm
        bundle:
          id: bundle_webm
          assets:
            - id: asset_webm
              role: main
              container: webm
              duration_seconds: 1.0
              matroska_muxing_profile: short_clusters
              video:
                source: color_bars
                codec: vp9
                resolution: sd
series: []
artists: []
timeline: []
"""


def _scenario_bytes(
    *,
    scenario_id: str,
    profiles: tuple[str, ...],
    title: str,
    timeline: str,
) -> bytes:
    profiles_yaml = "\n".join(f"  - {profile}" for profile in profiles)
    return f"""\
schema_version: 32
scenario_id: {scenario_id}
seed: 7
duration_scale: short
profiles:
{profiles_yaml}
library:
  roots:
    - id: movies_hd
      path: movies-hd
movies:
  - id: movie_001
    title: {title}
    layout: movie_flat
    variants:
      - id: variant_001
        label: hd
        bundle:
          id: bundle_001
          assets:
            - id: asset_main
              role: primary_video
              container: mkv
              duration_seconds: 1
              video:
                source: color_bars
                codec: h264
                resolution: hd
              audio:
                - codec: aac
                  channels: stereo
                  language: eng
series: []
artists: []
timeline:
{timeline}""".encode()


_SCENARIO = b"""\
schema_version: 32
scenario_id: run-replay-corruption-test
seed: 7
duration_scale: short
profiles:
  - malformed-media
library:
  roots:
    - id: movies_hd
      path: movies-hd
movies:
  - id: movie_001
    title: Broken Header
    layout: movie_flat
    variants:
      - id: variant_001
        label: hd
        bundle:
          id: bundle_001
          assets:
            - id: asset_main
              role: primary_video
              container: mkv
              duration_seconds: 1
              video:
                source: color_bars
                codec: h264
                resolution: hd
              audio:
                - codec: aac
                  channels: stereo
                  language: eng
series: []
artists: []
timeline:
  - id: corrupt_header_001
    at: 0ns
    action: corrupt_container_header
    target: asset_main
    bytes: 64
"""
_HDR_SCENARIO = b"""\
schema_version: 32
scenario_id: run-replay-hdr-capability-test
seed: 7
duration_scale: short
library:
  roots:
    - id: movies_hd
      path: movies-hd
movies:
  - id: movie_001
    title: HDR Replay
    layout: movie_flat
    variants:
      - id: variant_001
        label: hd
        bundle:
          id: bundle_001
          assets:
            - id: asset_main
              role: primary_video
              container: mkv
              duration_seconds: 1
              video:
                source: color_bars
                codec: hevc
                resolution: hd
                hdr_mode: hdr10
              audio:
                - codec: aac
                  channels: stereo
                  language: eng
series: []
artists: []
timeline: []
"""
_TRUNCATE_SCENARIO = _scenario_bytes(
    scenario_id="run-replay-truncate-test",
    profiles=("malformed-media",),
    title="Truncated File",
    timeline="""\
  - id: truncate_001
    at: 0ns
    action: truncate_file
    target: asset_main
    keep_bytes: 8
""",
)
_TOUCH_MTIME_SCENARIO = _scenario_bytes(
    scenario_id="run-replay-touch-mtime-test",
    profiles=("filesystem-artifacts",),
    title="Mtime Touch",
    timeline="""\
  - id: mtime_001
    at: 0ns
    action: touch_mtime
    target: asset_main
    offset: 2s
""",
)
_WRONG_ORACLE_SCENARIO = _scenario_bytes(
    scenario_id="run-replay-wrong-oracle-test",
    profiles=("negative-oracle",),
    title="Wrong Oracle",
    timeline="""\
  - id: wrong_hash_001
    at: 0ns
    action: wrong_oracle_hash
    target: asset_main
""",
)
_WRONG_ORACLE_FAILURE_SCENARIO = _scenario_bytes(
    scenario_id="run-replay-wrong-oracle-failure-test",
    profiles=("negative-oracle",),
    title="Wrong Oracle Failure",
    timeline="""\
  - id: wrong_hash_001
    at: 0ns
    action: wrong_oracle_hash
    target: asset_main
  - id: wrong_hash_002
    at: 1ns
    action: wrong_oracle_hash
    target: asset_main
""",
)
_NETWORK_LAG_SCENARIO = _scenario_bytes(
    scenario_id="run-replay-network-lag-test",
    profiles=("network-fs-lag",),
    title="Network Lag Replay",
    timeline="""\
  - id: rename_001
    at: 0ns
    action: rename_file
    target: asset_main
    to: movies-hd/renamed.mkv
  - id: lag_start_001
    at: 0ns
    action: network_lag_start
    effect: delayed_rename
    target: asset_main
    after: rename_001
    duration: 10ns
  - id: lag_commit_001
    at: 10ns
    action: network_lag_commit
    for: lag_start_001
""",
)

_NETWORK_FS_LOCK_SCENARIO = _scenario_bytes(
    scenario_id="run-replay-network-fs-lock-test",
    profiles=("network-fs-chaos",),
    title="Network FS Lock Replay",
    timeline="""\
  - id: acquire_001
    at: 0ns
    action: acquire_lock
    target: asset_main
    lock_type: exclusive
  - id: release_001
    at: 10ns
    action: release_lock
    for: acquire_001
""",
)


def test_run_replay_reproduces_corruption_action_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_replay_materializer(monkeypatch)

    artifacts = replay_run_bundle(_run_bundle(), tmp_path / "replay")

    assert artifacts.materialization_report.corruption_actions == [
        _corruption_action(
            output_version_id=artifacts.materialization_report.corruption_actions[
                0
            ].output_version_id
        )
    ]
    corrupted = _corrupted_version_payload(tmp_path / "replay")
    assert corrupted["content_hash"] == _CORRUPTED_HASH
    corruption = cast("dict[str, object]", corrupted["corruption"])
    assert corruption["event_id"] == "corrupt_header_001"
    report_payload = json.loads(
        (tmp_path / "replay" / "materialization.json").read_text(encoding="utf-8")
    )
    replay_payload = json.loads((tmp_path / "replay" / "replay.json").read_text(encoding="utf-8"))
    _assert_fake_content_source_payload(report_payload["content_sources"])
    _assert_fake_content_source_payload(replay_payload["content_sources"])


def test_run_replay_refuses_hdr_when_capability_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    caps = Capabilities(
        schema_version=CAPABILITIES_SCHEMA_VERSION,
        ffmpeg=ToolStatus(found=True, version="7.1.1", path="/x/ffmpeg", meets_minimum=True),
        ffprobe=ToolStatus(found=True, version="7.1.1", path="/x/ffprobe", meets_minimum=True),
        mkvtoolnix=ToolStatus(found=False, meets_minimum=False),
        platform="test",
        content_sources=ContentSourceCapabilities(),
        ready_for=ReadyFor(
            materialize_static=True,
            materialize_filesystem_mutations=True,
            materialize_media_mutations=True,
            materialize_hevc_video=True,
            materialize_hdr_video=False,
            materialize_resolution_switch_video=True,
            materialize_audio_recipes=True,
            materialize_matroska_muxing_profiles=True,
            materialize_webm_video=True,
        ),
    )
    monkeypatch.setattr(prep_mod, "detect_capabilities", lambda: caps)
    monkeypatch.setattr(
        replay_mod,
        "materialize_one_asset",
        lambda *_args, **_kwargs: pytest.fail("HDR gate should run before synthesis"),
    )
    out = tmp_path / "replay"

    with pytest.raises(CapabilityGateError) as exc:
        replay_run_bundle(_run_bundle_for(_HDR_SCENARIO, applied_events=0), out)

    assert exc.value.field == "ready_for.materialize_hdr_video"
    assert not out.exists()


def test_run_replay_refuses_resolution_switch_when_capability_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    caps = Capabilities(
        schema_version=CAPABILITIES_SCHEMA_VERSION,
        ffmpeg=ToolStatus(found=True, version="7.1.1", path="/x/ffmpeg", meets_minimum=True),
        ffprobe=ToolStatus(found=True, version="7.1.1", path="/x/ffprobe", meets_minimum=True),
        mkvtoolnix=ToolStatus(found=False, meets_minimum=False),
        platform="test",
        content_sources=ContentSourceCapabilities(),
        ready_for=ReadyFor(
            materialize_static=True,
            materialize_filesystem_mutations=True,
            materialize_media_mutations=True,
            materialize_hevc_video=True,
            materialize_hdr_video=True,
            materialize_resolution_switch_video=False,
            materialize_audio_recipes=True,
            materialize_matroska_muxing_profiles=True,
            materialize_webm_video=True,
        ),
    )
    monkeypatch.setattr(prep_mod, "detect_capabilities", lambda: caps)
    monkeypatch.setattr(
        replay_mod,
        "materialize_one_asset",
        lambda *_args, **_kwargs: pytest.fail("resolution-switch gate should run first"),
    )
    out = tmp_path / "replay"

    with pytest.raises(CapabilityGateError) as exc:
        replay_run_bundle(_run_bundle_for(_RESOLUTION_SWITCH_SCENARIO, applied_events=0), out)

    assert exc.value.field == "ready_for.materialize_resolution_switch_video"
    assert not out.exists()


def test_run_replay_refuses_audio_noise_when_capability_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    caps = Capabilities(
        schema_version=CAPABILITIES_SCHEMA_VERSION,
        ffmpeg=ToolStatus(found=True, version="7.1.1", path="/x/ffmpeg", meets_minimum=True),
        ffprobe=ToolStatus(found=True, version="7.1.1", path="/x/ffprobe", meets_minimum=True),
        mkvtoolnix=ToolStatus(found=False, meets_minimum=False),
        platform="test",
        content_sources=ContentSourceCapabilities(),
        ready_for=ReadyFor(
            materialize_static=True,
            materialize_filesystem_mutations=True,
            materialize_media_mutations=True,
            materialize_hevc_video=True,
            materialize_hdr_video=True,
            materialize_resolution_switch_video=True,
            materialize_audio_recipes=False,
            materialize_matroska_muxing_profiles=True,
            materialize_webm_video=True,
        ),
    )
    monkeypatch.setattr(prep_mod, "detect_capabilities", lambda: caps)
    monkeypatch.setattr(
        replay_mod,
        "materialize_one_asset",
        lambda *_args, **_kwargs: pytest.fail("audio recipe gate should run before synthesis"),
    )
    out = tmp_path / "replay"

    with pytest.raises(CapabilityGateError) as exc:
        replay_run_bundle(_run_bundle_for(AUDIO_NOISE_SCENARIO_BYTES, applied_events=0), out)

    assert exc.value.field == "ready_for.materialize_audio_recipes"
    assert exc.value.asset_id == "asset_noise"
    assert not out.exists()


@pytest.mark.parametrize(
    ("scenario", "muxing_ready", "webm_ready", "field", "asset_id"),
    [
        (
            _MKV_MUXING_PROFILE_SCENARIO,
            False,
            True,
            "ready_for.materialize_matroska_muxing_profiles",
            "asset_mux",
        ),
        (
            _WEBM_PROFILE_SCENARIO,
            True,
            False,
            "ready_for.materialize_webm_video",
            "asset_webm",
        ),
    ],
)
def test_run_replay_refuses_muxing_profile_capability_regressions(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    scenario: bytes,
    muxing_ready: bool,
    webm_ready: bool,
    field: str,
    asset_id: str,
) -> None:
    caps = Capabilities(
        schema_version=CAPABILITIES_SCHEMA_VERSION,
        ffmpeg=ToolStatus(found=True, version="7.1.1", path="/x/ffmpeg", meets_minimum=True),
        ffprobe=ToolStatus(found=True, version="7.1.1", path="/x/ffprobe", meets_minimum=True),
        mkvtoolnix=ToolStatus(found=True, version="80.0", path="/x/mkvmerge", meets_minimum=True),
        platform="test",
        content_sources=ContentSourceCapabilities(),
        ready_for=ReadyFor(
            materialize_static=True,
            materialize_filesystem_mutations=True,
            materialize_media_mutations=True,
            materialize_hevc_video=True,
            materialize_hdr_video=True,
            materialize_resolution_switch_video=True,
            materialize_audio_recipes=True,
            materialize_matroska_muxing_profiles=muxing_ready,
            materialize_webm_video=webm_ready,
        ),
    )
    monkeypatch.setattr(prep_mod, "detect_capabilities", lambda: caps)
    monkeypatch.setattr(
        replay_mod,
        "materialize_one_asset",
        lambda *_args, **_kwargs: pytest.fail("muxing profile gate should run first"),
    )
    out = tmp_path / "replay"

    with pytest.raises(CapabilityGateError) as exc:
        replay_run_bundle(_run_bundle_for(scenario, applied_events=0), out)

    assert exc.value.field == field
    assert exc.value.asset_id == asset_id
    assert not out.exists()


def test_run_replay_reproduces_truncate_file_corruption_action_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_replay_materializer(monkeypatch, patch_corruption=False)
    _patch_successful_truncate(monkeypatch)
    out = tmp_path / "replay"

    artifacts = replay_run_bundle(_run_bundle_for(_TRUNCATE_SCENARIO), out)

    action = artifacts.materialization_report.corruption_actions[0]
    assert action.action is TimelineActionName.TRUNCATE_FILE
    assert action.event_id == "truncate_001"
    assert action.corruptor == "truncate_file_v1"
    assert action.byte_start == 8
    assert action.byte_count == 8
    report_payload = json.loads((out / "materialization.json").read_text(encoding="utf-8"))
    assert report_payload["corruption_actions"][0]["action"] == "truncate_file"


def test_run_replay_reproduces_touch_mtime_filesystem_action_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_replay_materializer(monkeypatch)
    out = tmp_path / "replay"

    artifacts = replay_run_bundle(_run_bundle_for(_TOUCH_MTIME_SCENARIO), out)

    assert artifacts.materialization_report.corruption_actions == []
    action = artifacts.materialization_report.filesystem_actions[0]
    assert action.action is TimelineActionName.TOUCH_MTIME
    assert action.event_id == "mtime_001"
    assert action.content_hash is not None
    assert action.mtime_before_ns is not None
    assert action.mtime_after_ns == action.mtime_before_ns + 2_000_000_000
    report_payload = json.loads((out / "materialization.json").read_text(encoding="utf-8"))
    assert report_payload["filesystem_actions"][0]["action"] == "touch_mtime"


def test_run_replay_reproduces_wrong_oracle_hash_action_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_replay_materializer(monkeypatch)
    source = replay_run_bundle(_run_bundle_for(_WRONG_ORACLE_SCENARIO), tmp_path / "source")
    replayed = replay_run_bundle(source.replay_bundle, tmp_path / "replay")

    source_action = source.materialization_report.oracle_hash_actions[0]
    replayed_action = replayed.materialization_report.oracle_hash_actions[0]
    assert replayed_action.action is TimelineActionName.WRONG_ORACLE_HASH
    assert replayed_action.reported_content_hash == source_action.reported_content_hash
    latest = _latest_version_payload(tmp_path / "replay")
    assert latest["content_hash"] == source_action.reported_content_hash
    report_payload = json.loads(
        (tmp_path / "replay" / "materialization.json").read_text(encoding="utf-8")
    )
    assert report_payload["oracle_hash_actions"][0]["reported_content_hash"] == (
        source_action.reported_content_hash
    )


def test_run_replay_oracle_hash_failure_preserves_partial_actions(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_replay_materializer(monkeypatch)
    _patch_second_oracle_hash_failure(monkeypatch)
    out = tmp_path / "replay"

    with pytest.raises(CorruptionActionError, match="hash failed"):
        replay_run_bundle(_run_bundle_for(_WRONG_ORACLE_FAILURE_SCENARIO, applied_events=2), out)

    report = json.loads((out / "materialization.json").read_text(encoding="utf-8"))
    assert report["outcome"] == Outcome.CORRUPTION_FAILED.value
    assert report["oracle_hash_actions"][0]["event_id"] == "wrong_hash_001"
    assert report["oracle_hash_actions"][0]["reported_content_hash"] == "sha256:" + "9" * 64


def test_run_replay_rejects_mid_network_lag_prefix_before_creating_output(
    tmp_path: Path,
) -> None:
    out = tmp_path / "replay"

    with pytest.raises(ReplayIntegrityError, match="uncommitted network_lag_start"):
        replay_run_bundle(_run_bundle_for(_NETWORK_LAG_SCENARIO, applied_events=2), out)

    assert not out.exists()


def test_run_replay_rejects_mid_network_fs_window_before_creating_output(
    tmp_path: Path,
) -> None:
    out = tmp_path / "replay"

    with pytest.raises(ReplayIntegrityError, match="unclosed network-fs-chaos open windows"):
        replay_run_bundle(_run_bundle_for(_NETWORK_FS_LOCK_SCENARIO, applied_events=1), out)

    assert not out.exists()


def test_run_replay_reproduces_network_lag_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_replay_materializer(monkeypatch)
    out = tmp_path / "replay"

    artifacts = replay_run_bundle(
        _run_bundle_for(_NETWORK_LAG_SCENARIO, applied_events=3),
        out,
    )

    assert (out / "library" / "movies-hd" / "renamed.mkv").read_bytes() == (b"asset_main-bytes")
    action = artifacts.materialization_report.network_lag_actions[0]
    assert action.event_id == "lag_start_001"
    assert action.commit_event_id == "lag_commit_001"
    assert action.effect.value == "delayed_rename"
    assert action.after_event_id == "rename_001"
    assert action.from_path == "movies-hd/Network Lag Replay - hd.mkv"
    assert action.to_path == "movies-hd/renamed.mkv"
    assert action.provider == "stdlib-local"
    assert action.enforced is True

    report_payload = json.loads((out / "materialization.json").read_text(encoding="utf-8"))
    assert report_payload["network_lag_actions"][0]["event_id"] == "lag_start_001"


def test_run_replay_persists_regenerated_asset_reports(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_replay_materializer(monkeypatch)
    out = tmp_path / "replay"

    replay_run_bundle(_run_bundle(), out)

    manifest = json.loads((out / "manifest.current.json").read_text(encoding="utf-8"))
    asset_report = json.loads((out / "reports" / "assets" / "asset_main.json").read_text())
    corrupted = next(v for v in manifest["versions"] if v.get("corruption") is not None)
    assert asset_report["current"]["version_id"] == corrupted["id"]
    assert asset_report["current"]["content_hash"] == corrupted["content_hash"]
    assert asset_report["current"]["corruption"] == corrupted["corruption"]


def test_run_replay_corruption_failure_writes_corruption_failed_report(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_replay_materializer(monkeypatch)
    _patch_failing_corruption(monkeypatch)
    out = tmp_path / "replay"

    with pytest.raises(CorruptionActionError, match="short file"):
        replay_run_bundle(_run_bundle(), out)

    report = json.loads((out / "materialization.json").read_text(encoding="utf-8"))
    assert report["outcome"] == Outcome.CORRUPTION_FAILED.value
    assert report["execution_mode"] == "run"
    assert report["failures"][0]["stage"] == FailureStage.CORRUPTION.value
    assert report["failures"][0]["stderr_tail"] == "short file"
    _assert_fake_content_source_payload(report["content_sources"])
    replay_payload = json.loads((out / "replay.json").read_text(encoding="utf-8"))
    _assert_fake_content_source_payload(replay_payload["content_sources"])
    assert not (out / "library").exists()


def _run_bundle() -> MaterializeReplayBundle:
    return _run_bundle_for(_SCENARIO)


def _run_bundle_for(scenario: bytes, *, applied_events: int = 1) -> MaterializeReplayBundle:
    run_input = prepare_run_input_from_bytes(
        raw_bytes=scenario,
        source_label="run-replay-corruption",
    )
    report = run_validation(run_input)
    artifacts = run_materializer_plan(
        PlanExecutionRequest(
            run_input=run_input,
            validation_report=report,
            run_id_override=_RUN_ID,
            applied_events_override=applied_events,
        )
    )
    digest_entries = [
        entry.model_copy(update={"wall_clock_time": None}) for entry in artifacts.journal
    ]
    digest = hashlib.sha256(serialize_journal_bytes(digest_entries)).hexdigest()
    return MaterializeReplayBundle(
        schema_version=REPLAY_BUNDLE_SCHEMA_VERSION,
        chaos_librarian_version="0.1.0",
        scenario=scenario.decode("utf-8"),
        run_id=_RUN_ID,
        resolved_seed=artifacts.replay_bundle.resolved_seed,
        applied_events=applied_events,
        journal_digest=digest,
        execution_mode=ExecutionMode.RUN,
        created_at=datetime(2026, 5, 21, 0, 0, 0, tzinfo=UTC),
        toolchain=ToolchainInfo(ffmpeg="7.1.1", ffprobe="7.1.1"),
        content_sources=[],
    )


def _patch_replay_materializer(
    monkeypatch: pytest.MonkeyPatch,
    *,
    patch_corruption: bool = True,
) -> None:
    caps = Capabilities(
        schema_version=CAPABILITIES_SCHEMA_VERSION,
        ffmpeg=ToolStatus(found=True, version="7.1.1", path="/x/ffmpeg", meets_minimum=True),
        ffprobe=ToolStatus(found=True, version="7.1.1", path="/x/ffprobe", meets_minimum=True),
        mkvtoolnix=ToolStatus(found=False, meets_minimum=False),
        platform="test",
        content_sources=ContentSourceCapabilities(),
        ready_for=ReadyFor(
            materialize_static=True,
            materialize_filesystem_mutations=True,
            materialize_media_mutations=True,
            materialize_hevc_video=True,
            materialize_hdr_video=True,
            materialize_resolution_switch_video=True,
            materialize_audio_recipes=True,
            materialize_matroska_muxing_profiles=True,
            materialize_webm_video=True,
        ),
    )
    monkeypatch.setattr(prep_mod, "detect_capabilities", lambda: caps)
    monkeypatch.setattr(replay_mod, "materialize_one_asset", _fake_materialize_one_asset)
    if patch_corruption:
        _patch_successful_corruption(monkeypatch)


def _fake_materialize_one_asset(
    asset,
    resolved_seed,
    out_dir: Path,
    caps,
    invocation_index: int,
    *,
    rendered_relative_path: str,
    skip_languages=frozenset(),
):
    del resolved_seed, caps, skip_languages
    data = f"{asset.id}-bytes".encode()
    path = out_dir / "library" / rendered_relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    probed = ProbedMedia(
        container=asset.container,
        duration_seconds=asset.duration_seconds,
        size_bytes=len(data),
        streams=[ProbedStream(kind=StreamKind.VIDEO, codec="h264", width=1280, height=720)],
    )
    return MaterializeAssetResult(
        invocation=ToolInvocation(
            tool="ffmpeg",
            version="7.1.1",
            command=["ffmpeg", str(path)],
            exit_code=0,
            duration_ns=1,
        ),
        materialized_asset=MaterializedAsset(
            asset_id=asset.id,
            location_path=str(Path("library") / rendered_relative_path),
            content_hash="sha256:" + hashlib.sha256(data).hexdigest(),
            size_bytes=len(data),
            duration_seconds=asset.duration_seconds,
            invocation_index=invocation_index,
        ),
        probed=probed,
        sidecar_hashes={},
        content_sources=(_fake_content_source(asset.id),),
    )


def _fake_content_source(asset_id: str) -> ContentSourceEvidence:
    return ContentSourceEvidence(
        asset_id=asset_id,
        track_kind=ContentTrackKind.VIDEO,
        track_index=None,
        source="fake-video",
        provider=_FAKE_PROVIDER,
        recipe_digest=_FAKE_RECIPE_DIGEST,
        cache_disposition=CacheDisposition.NOT_CACHEABLE,
    )


def _assert_fake_content_source_payload(payload: list[dict[str, object]]) -> None:
    assert payload == [
        {
            "asset_id": "asset_main",
            "track_kind": "video",
            "source": "fake-video",
            "provider": _FAKE_PROVIDER,
            "recipe_digest": _FAKE_RECIPE_DIGEST,
            "cache_disposition": "not_cacheable",
        }
    ]


def _patch_successful_corruption(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_apply(ctx, entry: JournalEntry) -> CorruptionAction:
        output_version_id = entry.output_version_ids[0]
        ctx.post_phase_b_versions[output_version_id] = (
            _CORRUPTED_HASH,
            ProbedMedia(container="mkv", duration_seconds=1.0, size_bytes=128, streams=[]),
        )
        return _corruption_action(output_version_id=output_version_id)

    monkeypatch.setattr(dispatch_mod, "apply_corruption_action", fake_apply)


def _patch_successful_truncate(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_apply(ctx, entry: JournalEntry) -> CorruptionAction:
        output_version_id = entry.output_version_ids[0]
        ctx.post_phase_b_versions[output_version_id] = (
            _CORRUPTED_HASH,
            ProbedMedia(container="mkv", duration_seconds=1.0, size_bytes=8, streams=[]),
        )
        return CorruptionAction(
            event_id="truncate_001",
            action=TimelineActionName.TRUNCATE_FILE,
            target_asset_id="asset_main",
            input_path="movies-hd/Truncated File - hd.mkv",
            output_path="movies-hd/Truncated File - hd.mkv",
            input_version_id="version_0001",
            output_version_id=output_version_id,
            input_content_hash=_INPUT_HASH,
            output_content_hash=_CORRUPTED_HASH,
            corruptor="truncate_file_v1",
            input_size_bytes=16,
            output_size_bytes=8,
            byte_start=8,
            byte_count=8,
            seed_material="truncate_file_v1:7:truncate_001:asset_main",
            probe_outcome=CorruptionProbeOutcome.FAILED_EXPECTED,
            duration_ns=1,
        )

    monkeypatch.setattr(dispatch_mod, "apply_corruption_action", fake_apply)


def _patch_failing_corruption(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_apply(_ctx, entry: JournalEntry) -> CorruptionAction:
        raise CorruptionActionError(
            "corrupt_container_header failed for event corrupt_header_001: short file",
            event_id=entry.event_id,
            action=TimelineActionName.CORRUPT_CONTAINER_HEADER,
            cause=RuntimeError("short file"),
            asset_id=entry.target_ids[0],
        )

    monkeypatch.setattr(dispatch_mod, "apply_corruption_action", fake_apply)


def _patch_second_oracle_hash_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_apply(ctx, entry: JournalEntry) -> OracleHashAction:
        if entry.event_id == "wrong_hash_002":
            raise CorruptionActionError(
                "wrong_oracle_hash failed for event wrong_hash_002: hash failed",
                event_id=entry.event_id,
                action=TimelineActionName.WRONG_ORACLE_HASH,
                cause=RuntimeError("hash failed"),
                asset_id=entry.target_ids[0],
            )
        output_version_id = entry.output_version_ids[0]
        reported_hash = "sha256:" + "9" * 64
        ctx.post_phase_b_oracle_hashes[output_version_id] = (
            reported_hash,
            ProbedMedia(container="mkv", duration_seconds=1.0, size_bytes=16, streams=[]),
        )
        return OracleHashAction(
            event_id=entry.event_id,
            action=TimelineActionName.WRONG_ORACLE_HASH,
            target_asset_id=entry.target_ids[0],
            input_path="movies-hd/Wrong Oracle Failure - hd.mkv",
            output_path="movies-hd/Wrong Oracle Failure - hd.mkv",
            input_version_id=entry.input_version_ids[0],
            output_version_id=output_version_id,
            actual_content_hash=_INPUT_HASH,
            reported_content_hash=reported_hash,
            seed_material="wrong_oracle_hash_v1:7:wrong_hash_001:asset_main",
            duration_ns=1,
        )

    monkeypatch.setattr(dispatch_mod, "apply_wrong_oracle_hash", fake_apply)


def _corruption_action(*, output_version_id: str) -> CorruptionAction:
    return CorruptionAction(
        event_id="corrupt_header_001",
        action=TimelineActionName.CORRUPT_CONTAINER_HEADER,
        target_asset_id="asset_main",
        input_path="movies-hd/Broken Header - hd.mkv",
        output_path="movies-hd/Broken Header - hd.mkv",
        input_version_id="version_0001",
        output_version_id=output_version_id,
        input_content_hash=_INPUT_HASH,
        output_content_hash=_CORRUPTED_HASH,
        corruptor="container_header_v1",
        input_size_bytes=128,
        output_size_bytes=128,
        byte_start=0,
        byte_count=64,
        seed_material="container_header_v1:7:corrupt_header_001:asset_main",
        probe_outcome=CorruptionProbeOutcome.STILL_PROBEABLE,
        duration_ns=1,
    )


def _corrupted_version_payload(out_dir: Path) -> dict[str, object]:
    manifest = json.loads((out_dir / "manifest.current.json").read_text(encoding="utf-8"))
    for version in manifest["versions"]:
        if version.get("corruption") is not None:
            return version
    raise AssertionError("expected corrupted version in manifest.current.json")


def _latest_version_payload(out_dir: Path) -> dict[str, object]:
    manifest = json.loads((out_dir / "manifest.current.json").read_text(encoding="utf-8"))
    return cast("dict[str, object]", manifest["versions"][-1])
