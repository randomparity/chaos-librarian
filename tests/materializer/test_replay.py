"""Run replay materializer tests for Sprint 10 corruption evidence."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

from chaos_librarian.contract import REPLAY_BUNDLE_SCHEMA_VERSION
from chaos_librarian.contract.capabilities import Capabilities, ReadyFor, ToolStatus
from chaos_librarian.contract.journal import JournalEntry
from chaos_librarian.contract.manifest import ProbedMedia, ProbedStream, StreamKind
from chaos_librarian.contract.materialization import (
    CorruptionAction,
    FailureStage,
    MaterializedAsset,
    Outcome,
    ToolchainInfo,
    ToolInvocation,
)
from chaos_librarian.contract.profiles import CorruptionProbeOutcome
from chaos_librarian.contract.replay_bundle import ExecutionMode, MaterializeReplayBundle
from chaos_librarian.contract.scenario import TimelineActionName
from chaos_librarian.engine import run_plan
from chaos_librarian.engine.journal_io import serialize_journal_bytes
from chaos_librarian.materializer import phase_b
from chaos_librarian.materializer import replay as replay_mod
from chaos_librarian.materializer.errors import CorruptionActionError
from chaos_librarian.materializer.replay import replay_run_bundle
from chaos_librarian.validation import prepare_run_input_from_bytes, run_validation

_RUN_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
_CORRUPTED_HASH = "sha256:" + "2" * 64
_INPUT_HASH = "sha256:" + "1" * 64
_SCENARIO = b"""\
schema_version: 7
scenario_id: run-replay-corruption-test
seed: 7
duration_scale: short
profiles:
  - malformed-media
library:
  roots:
    - id: movies_hd
      path: movies-hd
works:
  - id: work_001
    title: Broken Header
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
timeline:
  - id: corrupt_header_001
    at: 0ns
    action: corrupt_container_header
    target: asset_main
    bytes: 64
"""


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
    assert not (out / "library").exists()


def _run_bundle() -> MaterializeReplayBundle:
    run_input = prepare_run_input_from_bytes(
        raw_bytes=_SCENARIO,
        source_label="run-replay-corruption",
    )
    report = run_validation(run_input)
    artifacts = run_plan(
        run_input=run_input,
        validation_report=report,
        run_id_override=_RUN_ID,
        applied_events_override=1,
    )
    digest_entries = [
        entry.model_copy(update={"wall_clock_time": None}) for entry in artifacts.journal
    ]
    digest = hashlib.sha256(serialize_journal_bytes(digest_entries)).hexdigest()
    return MaterializeReplayBundle(
        schema_version=REPLAY_BUNDLE_SCHEMA_VERSION,
        chaos_librarian_version="0.1.0",
        scenario=_SCENARIO.decode("utf-8"),
        run_id=_RUN_ID,
        resolved_seed=artifacts.replay_bundle.resolved_seed,
        applied_events=1,
        journal_digest=digest,
        execution_mode=ExecutionMode.RUN,
        created_at=datetime(2026, 5, 21, 0, 0, 0, tzinfo=UTC),
        toolchain=ToolchainInfo(ffmpeg="7.1.1", ffprobe="7.1.1"),
    )


def _patch_replay_materializer(monkeypatch: pytest.MonkeyPatch) -> None:
    caps = Capabilities(
        schema_version=1,
        ffmpeg=ToolStatus(found=True, version="7.1.1", path="/x/ffmpeg", meets_minimum=True),
        ffprobe=ToolStatus(found=True, version="7.1.1", path="/x/ffprobe", meets_minimum=True),
        mkvtoolnix=ToolStatus(found=False, meets_minimum=False),
        platform="test",
        ready_for=ReadyFor(
            materialize_static=True,
            materialize_filesystem_mutations=True,
            materialize_media_mutations=True,
        ),
    )
    monkeypatch.setattr(replay_mod, "detect_capabilities", lambda: caps)
    monkeypatch.setattr(replay_mod, "assert_capable_for_static_materialize", lambda _caps: None)
    monkeypatch.setattr(replay_mod, "materialize_one_asset", _fake_materialize_one_asset)
    _patch_successful_corruption(monkeypatch)


def _fake_materialize_one_asset(
    asset,
    resolved_seed,
    out_dir: Path,
    caps,
    invocation_index: int,
    *,
    root_path: str,
    skip_languages=frozenset(),
):
    del resolved_seed, caps, skip_languages
    data = f"{asset.id}-bytes".encode()
    path = out_dir / "library" / root_path / f"{asset.id}.{asset.container}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    probed = ProbedMedia(
        container=asset.container,
        duration_seconds=asset.duration_seconds,
        size_bytes=len(data),
        streams=[ProbedStream(kind=StreamKind.VIDEO, codec="h264", width=1280, height=720)],
    )
    return (
        ToolInvocation(
            tool="ffmpeg",
            version="7.1.1",
            command=["ffmpeg", str(path)],
            exit_code=0,
            duration_ns=1,
        ),
        MaterializedAsset(
            asset_id=asset.id,
            location_path=str(Path("library") / root_path / f"{asset.id}.{asset.container}"),
            content_hash="sha256:" + hashlib.sha256(data).hexdigest(),
            size_bytes=len(data),
            duration_seconds=asset.duration_seconds,
            invocation_index=invocation_index,
        ),
        probed,
        {},
    )


def _patch_successful_corruption(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_apply(ctx, entry: JournalEntry) -> CorruptionAction:
        output_version_id = entry.output_version_ids[0]
        ctx.post_phase_b_versions[output_version_id] = (
            _CORRUPTED_HASH,
            ProbedMedia(container="mkv", duration_seconds=1.0, size_bytes=128, streams=[]),
        )
        return _corruption_action(output_version_id=output_version_id)

    monkeypatch.setattr(phase_b, "apply_corruption_action", fake_apply)


def _patch_failing_corruption(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_apply(_ctx, entry: JournalEntry) -> CorruptionAction:
        raise CorruptionActionError(
            "corrupt_container_header failed for event corrupt_header_001: short file",
            event_id=entry.event_id,
            action=TimelineActionName.CORRUPT_CONTAINER_HEADER,
            cause=RuntimeError("short file"),
            asset_id=entry.target_ids[0],
        )

    monkeypatch.setattr(phase_b, "apply_corruption_action", fake_apply)


def _corruption_action(*, output_version_id: str) -> CorruptionAction:
    return CorruptionAction(
        event_id="corrupt_header_001",
        action=TimelineActionName.CORRUPT_CONTAINER_HEADER,
        target_asset_id="asset_main",
        input_path="movies-hd/asset_main.mkv",
        output_path="movies-hd/asset_main.mkv",
        input_version_id="version_0001",
        output_version_id=output_version_id,
        input_content_hash=_INPUT_HASH,
        output_content_hash=_CORRUPTED_HASH,
        corruptor="container_header_v1",
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
