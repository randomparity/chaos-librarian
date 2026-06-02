"""Materialize-report assembly helpers (run-level metadata + writer payloads)."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from chaos_librarian import __version__ as _chaos_librarian_version
from chaos_librarian.contract import (
    MATERIALIZATION_SCHEMA_VERSION,
    REPLAY_BUNDLE_SCHEMA_VERSION,
)
from chaos_librarian.contract.content_sources import ContentSourceEvidence
from chaos_librarian.contract.materialization import (
    MaterializationExecutionMode,
    MaterializationFailure,
    MaterializationReport,
    MaterializedAsset,
    Outcome,
    ToolchainInfo,
    ToolInvocation,
)
from chaos_librarian.contract.replay_bundle import ExecutionMode, MaterializeReplayBundle
from chaos_librarian.contract.run_sentinel import RunSentinel
from chaos_librarian.engine.plan import PlanArtifacts
from chaos_librarian.engine.reports import build_report_set
from chaos_librarian.materializer.persistence._context import ReportActions, RunContext
from chaos_librarian.materializer.persistence.writer import MaterializeMetadata, MaterializeReports

__all__ = [
    "MaterializationReportRequest",
    "ReplayBundleAssemblyRequest",
    "ReportInputs",
    "build_metadata",
    "build_replay_bundle",
    "build_report",
    "build_reports",
]


@dataclass(frozen=True, slots=True)
class ReportInputs:
    """Per-finalize report payload captured after materialization work completes."""

    finished_at: datetime
    invocations: list[ToolInvocation]
    materialized: list[MaterializedAsset]
    actions: ReportActions | None
    content_sources: list[ContentSourceEvidence]


@dataclass(frozen=True, slots=True)
class MaterializationReportRequest:
    """Inputs required to assemble one ``MaterializationReport``."""

    run_context: RunContext
    report_inputs: ReportInputs
    outcome: Outcome
    failures: list[MaterializationFailure]
    requested_duration_ns: int | None = None
    actual_duration_ns: int | None = None
    speed_multiplier: str | None = None
    overran_duration: bool = False
    execution_mode: MaterializationExecutionMode = MaterializationExecutionMode.MATERIALIZE


@dataclass(frozen=True, slots=True)
class ReplayBundleAssemblyRequest:
    """Inputs required to assemble one materialize/run replay bundle."""

    run_context: RunContext
    plan_artifacts: PlanArtifacts
    created_at: datetime
    content_sources: list[ContentSourceEvidence]
    execution_mode: Literal[ExecutionMode.MATERIALIZE, ExecutionMode.RUN] = (
        ExecutionMode.MATERIALIZE
    )


def build_report(request: MaterializationReportRequest) -> MaterializationReport:
    report_actions = request.report_inputs.actions or ReportActions()
    caps = request.run_context.caps
    return MaterializationReport(
        schema_version=MATERIALIZATION_SCHEMA_VERSION,
        run_id=request.run_context.run_id,
        outcome=request.outcome,
        platform=caps.platform,
        started_at=request.run_context.started_at,
        finished_at=request.report_inputs.finished_at,
        toolchain=ToolchainInfo(
            ffmpeg=caps.ffmpeg.version,
            ffprobe=caps.ffprobe.version,
            mkvtoolnix=caps.mkvtoolnix.version,
        ),
        content_sources=request.report_inputs.content_sources,
        invocations=request.report_inputs.invocations,
        materialized=request.report_inputs.materialized,
        failures=request.failures,
        filesystem_actions=report_actions.filesystem,
        media_actions=report_actions.media,
        corruption_actions=report_actions.corruption,
        oracle_hash_actions=report_actions.oracle_hash,
        network_lag_actions=report_actions.network_lag,
        network_fs_chaos_actions=report_actions.network_fs_chaos,
        requested_duration_ns=request.requested_duration_ns,
        actual_duration_ns=request.actual_duration_ns,
        speed_multiplier=request.speed_multiplier,
        overran_duration=request.overran_duration,
        execution_mode=request.execution_mode,
    )


def build_replay_bundle(request: ReplayBundleAssemblyRequest) -> MaterializeReplayBundle:
    caps = request.run_context.caps
    return MaterializeReplayBundle(
        schema_version=REPLAY_BUNDLE_SCHEMA_VERSION,
        chaos_librarian_version=_chaos_librarian_version,
        scenario=request.run_context.run_input.raw_bytes.decode("utf-8"),
        run_id=request.run_context.run_id,
        resolved_seed=request.plan_artifacts.replay_bundle.resolved_seed,
        applied_events=request.plan_artifacts.replay_bundle.applied_events,
        journal_digest=request.plan_artifacts.replay_bundle.journal_digest,
        execution_mode=request.execution_mode,
        created_at=request.created_at,
        toolchain=ToolchainInfo(
            ffmpeg=caps.ffmpeg.version,
            ffprobe=caps.ffprobe.version,
            mkvtoolnix=caps.mkvtoolnix.version,
        ),
        content_sources=request.content_sources,
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
        assets=_required_report_map(reports, "assets", "asset_id"),
        movies=_required_report_map(reports, "movies", "movie_id"),
        series=_required_report_map(reports, "series", "series_id"),
        seasons=_required_report_map(reports, "seasons", "season_id"),
        episodes=_required_report_map(reports, "episodes", "episode_id"),
        artists=_required_report_map(reports, "artists", "artist_id"),
        albums=_required_report_map(reports, "albums", "album_id"),
        discs=_required_report_map(reports, "discs", "disc_id"),
        tracks=_required_report_map(reports, "tracks", "track_id"),
        variants=_required_report_map(reports, "variants", "variant_id"),
        bundles=_required_report_map(reports, "bundles", "bundle_id"),
    )


def _required_report_map[T: BaseModel](
    report_set: object,
    name: str,
    id_field: str,
) -> dict[str, T]:
    if not hasattr(report_set, name):
        raise ValueError(f"report set is missing required {name} reports")
    return _report_map(getattr(report_set, name), id_field)


def _report_map[T: BaseModel](reports: Iterable[T], id_field: str) -> dict[str, T]:
    mapped: dict[str, T] = {}
    for report in reports:
        report_id = getattr(report, id_field)
        if not isinstance(report_id, str):
            raise TypeError(f"{id_field} must be a string")
        mapped[report_id] = report
    return mapped
