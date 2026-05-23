"""Materialize-report assembly helpers (run-level metadata + writer payloads)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from chaos_librarian import __version__ as _chaos_librarian_version
from chaos_librarian.contract import (
    MATERIALIZATION_SCHEMA_VERSION,
    REPLAY_BUNDLE_SCHEMA_VERSION,
)
from chaos_librarian.contract.capabilities import Capabilities
from chaos_librarian.contract.materialization import (
    CorruptionAction,
    FilesystemAction,
    MaterializationExecutionMode,
    MaterializationFailure,
    MaterializationReport,
    MaterializedAsset,
    MediaAction,
    Outcome,
    ToolchainInfo,
    ToolInvocation,
)
from chaos_librarian.contract.replay_bundle import ExecutionMode, MaterializeReplayBundle
from chaos_librarian.contract.run_sentinel import RunSentinel
from chaos_librarian.engine import PlanArtifacts
from chaos_librarian.engine.reports import build_report_set
from chaos_librarian.materializer.persistence.writer import MaterializeMetadata, MaterializeReports

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
    media_actions: list[MediaAction] | None = None,
    corruption_actions: list[CorruptionAction] | None = None,
    requested_duration_ns: int | None = None,
    actual_duration_ns: int | None = None,
    speed_multiplier: str | None = None,
    overran_duration: bool = False,
    execution_mode: MaterializationExecutionMode = MaterializationExecutionMode.MATERIALIZE,
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
        media_actions=media_actions or [],
        corruption_actions=corruption_actions or [],
        requested_duration_ns=requested_duration_ns,
        actual_duration_ns=actual_duration_ns,
        speed_multiplier=speed_multiplier,
        overran_duration=overran_duration,
        execution_mode=execution_mode,
    )


def build_replay_bundle(
    *,
    run_id: uuid.UUID,
    scenario_yaml_bytes: bytes,
    plan_artifacts: PlanArtifacts,
    caps: Capabilities,
    created_at: datetime,
    execution_mode: Literal[ExecutionMode.MATERIALIZE, ExecutionMode.RUN] = (
        ExecutionMode.MATERIALIZE
    ),
) -> MaterializeReplayBundle:
    return MaterializeReplayBundle(
        schema_version=REPLAY_BUNDLE_SCHEMA_VERSION,
        chaos_librarian_version=_chaos_librarian_version,
        scenario=scenario_yaml_bytes.decode("utf-8"),
        run_id=run_id,
        resolved_seed=plan_artifacts.replay_bundle.resolved_seed,
        applied_events=plan_artifacts.replay_bundle.applied_events,
        journal_digest=plan_artifacts.replay_bundle.journal_digest,
        execution_mode=execution_mode,
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
    """Build writer report dicts from final manifests."""
    reports = build_report_set(
        initial=plan_artifacts.initial_manifest,
        current=plan_artifacts.current_manifest,
        journal=plan_artifacts.journal,
    )
    return MaterializeReports(
        assets={r.asset_id: r for r in reports.assets},
        works={r.work_id: r for r in reports.works},
        variants={r.variant_id: r for r in reports.variants},
        bundles={r.bundle_id: r for r in reports.bundles},
    )
