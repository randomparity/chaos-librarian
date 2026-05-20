"""Materialize-report assembly helpers (run-level metadata + writer payloads)."""

from __future__ import annotations

import uuid
from datetime import datetime

from chaos_librarian import __version__ as _chaos_librarian_version
from chaos_librarian.contract import (
    MATERIALIZATION_SCHEMA_VERSION,
    REPLAY_BUNDLE_SCHEMA_VERSION,
)
from chaos_librarian.contract.capabilities import Capabilities
from chaos_librarian.contract.materialization import (
    FilesystemAction,
    MaterializationFailure,
    MaterializationReport,
    MaterializedAsset,
    Outcome,
    ToolchainInfo,
    ToolInvocation,
)
from chaos_librarian.contract.replay_bundle import ExecutionMode, MaterializeReplayBundle
from chaos_librarian.contract.run_sentinel import RunSentinel
from chaos_librarian.engine import PlanArtifacts
from chaos_librarian.materializer.writer import MaterializeMetadata, MaterializeReports

__all__ = ["build_metadata", "build_replay_bundle", "build_report", "build_reports"]


def build_report(
    *,
    outcome: Outcome,
    run_id: uuid.UUID,
    caps: Capabilities,
    started_at: datetime,
    finished_at: datetime,
    invocations: list[ToolInvocation],
    materialized: list[MaterializedAsset],
    failures: list[MaterializationFailure],
    filesystem_actions: list[FilesystemAction] | None = None,
) -> MaterializationReport:
    return MaterializationReport(
        schema_version=MATERIALIZATION_SCHEMA_VERSION,
        run_id=run_id,
        outcome=outcome,
        platform=caps.platform,
        started_at=started_at,
        finished_at=finished_at,
        toolchain=ToolchainInfo(
            ffmpeg=caps.ffmpeg.version,
            ffprobe=caps.ffprobe.version,
            mkvtoolnix=caps.mkvtoolnix.version,
        ),
        invocations=invocations,
        materialized=materialized,
        failures=failures,
        filesystem_actions=filesystem_actions or [],
    )


def build_replay_bundle(
    *,
    run_id: uuid.UUID,
    scenario_yaml_bytes: bytes,
    plan_artifacts: PlanArtifacts,
    caps: Capabilities,
    created_at: datetime,
) -> MaterializeReplayBundle:
    return MaterializeReplayBundle(
        schema_version=REPLAY_BUNDLE_SCHEMA_VERSION,
        chaos_librarian_version=_chaos_librarian_version,
        scenario=scenario_yaml_bytes.decode("utf-8"),
        run_id=run_id,
        resolved_seed=plan_artifacts.replay_bundle.resolved_seed,
        journal_digest=plan_artifacts.replay_bundle.journal_digest,
        execution_mode=ExecutionMode.MATERIALIZE,
        created_at=created_at,
        toolchain=ToolchainInfo(
            ffmpeg=caps.ffmpeg.version,
            ffprobe=caps.ffprobe.version,
            mkvtoolnix=caps.mkvtoolnix.version,
        ),
    )


def build_metadata(
    *,
    plan_artifacts: PlanArtifacts,
    scenario_yaml_bytes: bytes,
    materialization_report: MaterializationReport,
    replay_bundle: MaterializeReplayBundle,
    sentinel: RunSentinel,
) -> MaterializeMetadata:
    """Assemble the shared writer payload (success and failure paths)."""
    return MaterializeMetadata(
        initial_manifest=plan_artifacts.initial_manifest,
        current_manifest=plan_artifacts.current_manifest,
        journal_entries=plan_artifacts.journal,
        validation_report=plan_artifacts.validation_report,
        materialization_report=materialization_report,
        replay_bundle=replay_bundle,
        scenario_yaml_bytes=scenario_yaml_bytes,
        sentinel=sentinel,
    )


def build_reports(plan_artifacts: PlanArtifacts) -> MaterializeReports:
    """Convert the engine's tuple-of-reports into the writer's id→report dicts."""
    reports = plan_artifacts.reports
    return MaterializeReports(
        assets={r.asset_id: r for r in reports.assets},
        works={r.work_id: r for r in reports.works},
        variants={r.variant_id: r for r in reports.variants},
        bundles={r.bundle_id: r for r in reports.bundles},
    )
