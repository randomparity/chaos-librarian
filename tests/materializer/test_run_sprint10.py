"""Sprint 10 materializer report regeneration and corruption routing tests."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from chaos_librarian import __version__ as _chaos_librarian_version
from chaos_librarian.contract import REPLAY_BUNDLE_SCHEMA_VERSION
from chaos_librarian.contract.capabilities import Capabilities, ReadyFor, ToolStatus
from chaos_librarian.contract.content_sources import ContentSourceCapabilities
from chaos_librarian.contract.journal import JournalEntry
from chaos_librarian.contract.manifest import (
    Manifest,
    ManifestAsset,
    ManifestBundle,
    ManifestLocation,
    ManifestVariant,
    ManifestVersion,
    ManifestWork,
    ProbedMedia,
)
from chaos_librarian.contract.materialization import (
    CorruptionAction,
    FailureStage,
    Outcome,
    ToolInvocation,
)
from chaos_librarian.contract.profiles import (
    CorruptionProbeOutcome,
    CorruptionRecord,
    ProfileName,
)
from chaos_librarian.contract.replay_bundle import ExecutionMode, PlanOnlyReplayBundle
from chaos_librarian.contract.run_sentinel import RunSentinel
from chaos_librarian.contract.scenario import TimelineActionName
from chaos_librarian.contract.validation import ValidationReport
from chaos_librarian.engine import PlanArtifacts
from chaos_librarian.engine.reports import build_report_set
from chaos_librarian.materializer import phase_b
from chaos_librarian.materializer import run as run_mod
from chaos_librarian.materializer import synthesis as synthesis_mod
from chaos_librarian.materializer.errors import CorruptionActionError
from chaos_librarian.materializer.persistence.reports import build_reports
from chaos_librarian.materializer.phase_b.corruption import CorruptionPhaseBContext
from chaos_librarian.materializer.run import materialize_scenario

_RUN_ID = uuid.UUID("1d4f7e6c-4e2e-4f1c-9a4c-7d2a9c8e0f01")
_CORRUPTED_HASH = "sha256:" + "2" * 64
_INPUT_HASH = "sha256:" + "1" * 64


_MALFORMED_SCENARIO = """\
schema_version: 7
scenario_id: malformed-materialize-test
seed: 42
duration_scale: short
profiles:
  - malformed-media
library:
  roots:
    - id: r0
      path: movies-hd
works:
  - id: w0
    title: Broken Header
    variants:
      - id: v0
        label: hd
        bundle:
          id: b0
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
    at: 1s
    action: corrupt_container_header
    target: asset_main
    bytes: 64
"""


def _corruption_record() -> CorruptionRecord:
    return CorruptionRecord(
        profile=ProfileName.MALFORMED_MEDIA,
        event_id="corrupt_header_001",
        corruptor="container_header_v1",
        byte_start=0,
        byte_count=64,
        seed_material="container_header_v1:42:corrupt_header_001:asset_main",
    )


def _manifest(*, corrupted: bool) -> Manifest:
    versions = [ManifestVersion(id="version_0001", asset_id="asset_main", index=0)]
    if corrupted:
        versions.append(
            ManifestVersion(
                id="version_0002",
                asset_id="asset_main",
                index=1,
                content_hash="sha256:" + "2" * 64,
                corruption=_corruption_record(),
            )
        )
    return Manifest(
        schema_version=5,
        works=[ManifestWork(id="work_001", title="Broken Header")],
        variants=[ManifestVariant(id="variant_hd", work_id="work_001", label="hd")],
        bundles=[ManifestBundle(id="bundle_hd", variant_id="variant_hd")],
        assets=[
            ManifestAsset(
                id="asset_main",
                bundle_id="bundle_hd",
                role="primary_video",
                container="mkv",
                duration_seconds=1,
            )
        ],
        versions=versions,
        locations=[
            ManifestLocation(id="location_0001", asset_id="asset_main", path="movies-hd/a.mkv")
        ],
        sidecars=[],
    )


def _plan_artifacts_with_stale_reports() -> PlanArtifacts:
    initial = _manifest(corrupted=False)
    current = _manifest(corrupted=True)
    stale_reports = build_report_set(initial=initial, current=initial, journal=[])
    return PlanArtifacts(
        initial_manifest=initial,
        current_manifest=current,
        journal=(),
        replay_bundle=PlanOnlyReplayBundle(
            schema_version=REPLAY_BUNDLE_SCHEMA_VERSION,
            chaos_librarian_version=_chaos_librarian_version,
            scenario="schema_version: 7\n",
            run_id=_RUN_ID,
            resolved_seed=42,
            applied_events=0,
            journal_digest="0" * 64,
            execution_trace=[],
            execution_mode=ExecutionMode.PLAN_ONLY,
        ),
        validation_report=ValidationReport(
            schema_version=1,
            scenario_id="materialize-report-test",
            ok=True,
            issues=[],
        ),
        sentinel=RunSentinel(
            schema_version=2,
            run_id=_RUN_ID,
            created_by="chaos-librarian test",
        ),
        reports=stale_reports,
    )


def test_materialize_reports_rebuild_from_augmented_manifest() -> None:
    reports = build_reports(_plan_artifacts_with_stale_reports())

    current = reports.assets["asset_main"].current
    assert current is not None
    assert current.version_id == "version_0002"
    assert current.content_hash == "sha256:" + "2" * 64
    assert current.corruption == _corruption_record()


def test_materialize_corruption_writes_manifest_and_report_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_successful_synthesis(monkeypatch)
    _patch_successful_corruption(monkeypatch)
    scenario = _write_scenario(tmp_path)
    out = tmp_path / "run-001"

    artifacts = materialize_scenario(scenario, out)

    corrupted = _corrupted_version(artifacts.current_manifest)
    assert corrupted.content_hash == _CORRUPTED_HASH
    assert corrupted.probed == _probed()
    assert corrupted.corruption == _corruption_record()
    assert artifacts.materialization_report.outcome is Outcome.SUCCESS
    assert artifacts.materialization_report.corruption_actions[0].output_version_id == corrupted.id


def test_materialize_writes_one_corruption_action(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_successful_synthesis(monkeypatch)
    _patch_successful_corruption(monkeypatch)
    out = tmp_path / "run-001"

    artifacts = materialize_scenario(_write_scenario(tmp_path), out)

    assert artifacts.materialization_report.corruption_actions == [
        _corruption_action(artifacts.materialization_report.corruption_actions[0].output_version_id)
    ]
    persisted = json.loads((out / "materialization.json").read_text())
    assert persisted["corruption_actions"][0]["event_id"] == "corrupt_header_001"
    assert persisted["corruption_actions"][0]["output_content_hash"] == _CORRUPTED_HASH


def test_materialize_persisted_asset_report_matches_current_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_successful_synthesis(monkeypatch)
    _patch_successful_corruption(monkeypatch)
    out = tmp_path / "run-001"

    materialize_scenario(_write_scenario(tmp_path), out)

    manifest = json.loads((out / "manifest.current.json").read_text())
    asset_report = json.loads((out / "reports" / "assets" / "asset_main.json").read_text())
    corrupted = next(v for v in manifest["versions"] if v.get("corruption") is not None)
    assert asset_report["current"]["version_id"] == corrupted["id"]
    assert asset_report["current"]["content_hash"] == corrupted["content_hash"]
    assert asset_report["current"]["corruption"] == corrupted["corruption"]


def test_corruption_failure_writes_corruption_failed_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_successful_synthesis(monkeypatch)
    _patch_failing_corruption(monkeypatch)
    out = tmp_path / "run-001"

    with pytest.raises(CorruptionActionError):
        materialize_scenario(_write_scenario(tmp_path), out)

    assert not (out / "library").exists()
    body = json.loads((out / "materialization.json").read_text())
    assert body["outcome"] == Outcome.CORRUPTION_FAILED.value
    assert body["failures"][0]["stage"] == FailureStage.CORRUPTION.value
    assert body["failures"][0]["stderr_tail"] == "short file"


def _write_scenario(tmp_path: Path) -> Path:
    path = tmp_path / "malformed.yaml"
    path.write_text(_MALFORMED_SCENARIO)
    return path


def _patch_successful_synthesis(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(
        argv: list[str], *, ffmpeg_version: str, timeout_s: float = 60.0
    ) -> tuple[ToolInvocation, str]:
        del timeout_s
        Path(argv[-1]).write_bytes(b"x" * 128)
        return (
            ToolInvocation(
                tool="ffmpeg",
                version=ffmpeg_version,
                command=list(argv),
                exit_code=0,
                duration_ns=1,
            ),
            "",
        )

    monkeypatch.setattr(synthesis_mod, "run_ffmpeg", fake_run)
    monkeypatch.setattr(synthesis_mod, "probe_file", lambda _path: _probed())
    monkeypatch.setattr(run_mod, "detect_capabilities", _fake_capabilities)


def _fake_capabilities() -> Capabilities:
    return Capabilities(
        schema_version=2,
        ffmpeg=ToolStatus(found=True, version="7.1.1", path="/x/ffmpeg", meets_minimum=True),
        ffprobe=ToolStatus(found=True, version="7.1.1", path="/x/ffprobe", meets_minimum=True),
        mkvtoolnix=ToolStatus(found=False, meets_minimum=False),
        platform="test",
        content_sources=ContentSourceCapabilities(),
        ready_for=ReadyFor(
            materialize_static=True,
            materialize_filesystem_mutations=True,
            materialize_media_mutations=False,
        ),
    )


def _patch_successful_corruption(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_apply(ctx: CorruptionPhaseBContext, entry: JournalEntry) -> CorruptionAction:
        output_version_id = entry.output_version_ids[0]
        ctx.post_phase_b_versions[output_version_id] = (_CORRUPTED_HASH, _probed())
        return _corruption_action(output_version_id)

    monkeypatch.setattr(phase_b, "apply_corruption_action", fake_apply)


def _patch_failing_corruption(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_apply(_ctx: CorruptionPhaseBContext, entry: JournalEntry) -> CorruptionAction:
        raise CorruptionActionError(
            "corrupt_container_header failed for event corrupt_header_001: short file",
            event_id=entry.event_id,
            action=TimelineActionName.CORRUPT_CONTAINER_HEADER,
            cause=RuntimeError("short file"),
            asset_id=entry.target_ids[0],
        )

    monkeypatch.setattr(phase_b, "apply_corruption_action", fake_apply)


def _probed() -> ProbedMedia:
    return ProbedMedia(container="matroska", duration_seconds=1.0, size_bytes=128, streams=[])


def _corruption_action(output_version_id: str) -> CorruptionAction:
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
        seed_material="container_header_v1:42:corrupt_header_001:asset_main",
        probe_outcome=CorruptionProbeOutcome.STILL_PROBEABLE,
        duration_ns=1,
    )


def _corrupted_version(manifest: Manifest) -> ManifestVersion:
    for version in manifest.versions:
        if version.corruption is not None:
            return version
    raise AssertionError("expected a corrupted manifest version")
