"""Sprint 10 materializer report regeneration tests."""

from __future__ import annotations

import uuid

from chaos_librarian import __version__ as _chaos_librarian_version
from chaos_librarian.contract.manifest import (
    Manifest,
    ManifestAsset,
    ManifestBundle,
    ManifestLocation,
    ManifestVariant,
    ManifestVersion,
    ManifestWork,
)
from chaos_librarian.contract.profiles import CorruptionRecord, ProfileName
from chaos_librarian.contract.replay_bundle import ExecutionMode, PlanOnlyReplayBundle
from chaos_librarian.contract.run_sentinel import RunSentinel
from chaos_librarian.contract.validation import ValidationReport
from chaos_librarian.engine import PlanArtifacts
from chaos_librarian.engine.reports import build_report_set
from chaos_librarian.materializer.reports import build_reports

_RUN_ID = uuid.UUID("1d4f7e6c-4e2e-4f1c-9a4c-7d2a9c8e0f01")


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
            schema_version=5,
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
