"""Materialization report schema (v9).

Carries started_at/finished_at, platform, structured ToolchainInfo,
per-asset MaterializedAsset records, per-failure MaterializationFailure
records, per-source ContentSourceEvidence records, per-phase-B
FilesystemAction and MediaAction audit records, and an Outcome enum that
includes an explicit ``success`` signal.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from chaos_librarian.contract.content_sources import ContentSourceEvidence
from chaos_librarian.contract.patterns import SHA256_URI_PATTERN
from chaos_librarian.contract.profiles import CorruptionProbeOutcome
from chaos_librarian.contract.scenario import (
    LockType,
    Mp4MoovPlacement,
    NetworkLagEffect,
    ReadonlyState,
    TimelineActionName,
)


class NetworkFsChaosCondition(enum.StrEnum):
    """The neutral errno / condition a network-fs-chaos action injects.

    Recorded as a fact in ``NetworkFsChaosAction``; chaos-librarian attaches no
    expected consumer verdict to it.
    """

    EACCES = "eacces"
    ENOSPC = "enospc"
    ESTALE = "estale"
    EAGAIN = "eagain"
    UNAVAILABLE = "unavailable"


class Outcome(enum.StrEnum):
    """High-level materialize result.

    ``unsupported`` covers both timeline-rejection and matrix-rejection.
    ``tool_failed`` covers both ffmpeg subprocess errors and ffprobe parse
    failures.
    """

    SUCCESS = "success"
    UNSUPPORTED = "unsupported"
    TOOL_FAILED = "tool_failed"
    TOOL_MISSING = "tool_missing"
    CONTAINMENT_VIOLATION = "containment_violation"
    FS_FAILED = "fs_failed"
    MEDIA_FAILED = "media_failed"
    CORRUPTION_FAILED = "corruption_failed"


class FailureStage(enum.StrEnum):
    """Subprocess stage that produced a MaterializationFailure."""

    FFMPEG = "ffmpeg"
    FFPROBE = "ffprobe"
    FILESYSTEM = "filesystem"
    MEDIA = "media"
    CORRUPTION = "corruption"


class MaterializationExecutionMode(enum.StrEnum):
    """Mode that produced the materialization report."""

    MATERIALIZE = "materialize"
    RUN = "run"


class ToolchainInfo(BaseModel):
    """Versions of the external tools used during materialization.

    Shared with ``MaterializeReplayBundle`` so consumers see one shape.
    Every field is optional because a tool may be missing on a system
    that nevertheless succeeded at static materialize (for example,
    mkvtoolnix is only required for media-mutation modes).
    """

    model_config = ConfigDict(extra="forbid")

    ffmpeg: str | None = None
    ffprobe: str | None = None
    mkvtoolnix: str | None = None


class ToolInvocation(BaseModel):
    """One subprocess invocation captured for the replay bundle and report."""

    model_config = ConfigDict(extra="forbid")

    tool: str
    version: str
    command: list[str]
    exit_code: int
    duration_ns: int


class MaterializedAsset(BaseModel):
    """Per-asset success record."""

    model_config = ConfigDict(extra="forbid")

    asset_id: str
    location_path: str
    content_hash: str
    size_bytes: int
    duration_seconds: float
    invocation_index: int
    mp4_moov_placement: Mp4MoovPlacement | None = None


class MaterializationFailure(BaseModel):
    """Per-failure record.

    ``asset_id`` is None for non-per-asset stages (e.g. capability
    regression). ``invocation_index`` indexes into ``invocations`` when the
    failure came from a subprocess call.
    """

    model_config = ConfigDict(extra="forbid")

    asset_id: str | None = None
    stage: FailureStage
    exit_code: int | None = None
    stderr_tail: str
    invocation_index: int | None = None


class FilesystemAction(BaseModel):
    """One phase-B filesystem operation audit record.

    Mirrors ``ToolInvocation``'s role for subprocesses: one record per
    journal entry that produced a real disk change.
    """

    model_config = ConfigDict(extra="forbid")

    event_id: str
    action: TimelineActionName
    target_asset_id: str
    from_path: str | None = None
    to_path: str | None = None
    temp_path: str | None = None
    content_hash: str | None = Field(default=None, pattern=SHA256_URI_PATTERN)
    mtime_before_ns: int | None = None
    mtime_after_ns: int | None = None
    duration_ns: int


class MediaAction(BaseModel):
    """One phase-B media operation audit record.

    Parallel to ``FilesystemAction``: one record per journal entry that
    produced a real byte / probed-metadata change via ffmpeg or
    sidecar-regeneration. ``tool_invocation_index`` cross-refs into
    ``MaterializationReport.invocations`` so consumers can join the two
    audit streams.
    """

    model_config = ConfigDict(extra="forbid")

    event_id: str
    action: TimelineActionName
    target_asset_id: str
    input_path: str
    output_path: str
    input_version_id: str | None = None
    output_version_id: str | None = None
    output_sidecar_id: str | None = None
    input_content_hash: str | None = Field(default=None, pattern=SHA256_URI_PATTERN)
    output_content_hash: str | None = Field(default=None, pattern=SHA256_URI_PATTERN)
    tool_invocation_index: int | None = None
    duration_ns: int


class CorruptionAction(BaseModel):
    """One phase-B intentional corruption audit record."""

    model_config = ConfigDict(extra="forbid")

    event_id: str
    action: Literal[
        TimelineActionName.CORRUPT_CONTAINER_HEADER,
        TimelineActionName.TRUNCATE_FILE,
        TimelineActionName.CORRUPT_PACKET_RANGE,
        TimelineActionName.WRITE_INVALID_DURATION_METADATA,
    ]
    target_asset_id: str
    input_path: str
    output_path: str
    input_version_id: str | None = None
    output_version_id: str
    input_content_hash: str = Field(pattern=SHA256_URI_PATTERN)
    output_content_hash: str = Field(pattern=SHA256_URI_PATTERN)
    corruptor: str
    input_size_bytes: int
    output_size_bytes: int
    byte_start: int | None = None
    byte_count: int | None = None
    seed_material: str | None = None
    stream: str | None = None
    packet_start: int | None = None
    packet_count: int | None = None
    metadata: dict[str, str | int | float | bool] = Field(default_factory=dict)
    probe_outcome: CorruptionProbeOutcome
    probe_error_tail: str | None = None
    duration_ns: int


class OracleHashAction(BaseModel):
    """One negative-oracle audit record with divergent reported hash."""

    model_config = ConfigDict(extra="forbid")

    event_id: str
    action: Literal[TimelineActionName.WRONG_ORACLE_HASH]
    target_asset_id: str
    input_path: str
    output_path: str
    input_version_id: str | None = None
    output_version_id: str
    actual_content_hash: str = Field(pattern=SHA256_URI_PATTERN)
    reported_content_hash: str = Field(pattern=SHA256_URI_PATTERN)
    seed_material: str
    duration_ns: int


class NetworkLagAction(BaseModel):
    """One watcher-visible network filesystem lag audit record."""

    model_config = ConfigDict(extra="forbid")

    event_id: str
    commit_event_id: str
    effect: NetworkLagEffect
    target_ref: str
    after_event_id: str
    logical_start_ns: int
    logical_commit_ns: int
    requested_duration_ns: int
    actual_duration_ns: int | None = None
    from_path: str | None = None
    to_path: str | None = None
    provider: str
    enforced: bool


class NetworkFsChaosAction(BaseModel):
    """One network-filesystem chaos audit record (neutral injected condition).

    Records what condition was injected, on what target, and whether it was
    really enforced on disk (a real ``os.chmod`` for permissions/readonly) or
    only recorded (the kernel-level conditions). Carries no expected consumer
    verdict — the consumer's adapter reads the condition and applies its own
    policy.
    """

    model_config = ConfigDict(extra="forbid")

    event_id: str
    action: TimelineActionName
    target_ref: str
    condition: NetworkFsChaosCondition
    enforced: bool
    mode: str | None = None
    readonly_state: ReadonlyState | None = None
    lock_type: LockType | None = None
    related_event_id: str | None = None
    related_target_ref: str | None = None


class MaterializationReport(BaseModel):
    """Top-level ``materialization.json`` body."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[17]
    run_id: uuid.UUID
    outcome: Outcome
    platform: str
    started_at: datetime
    finished_at: datetime
    toolchain: ToolchainInfo
    content_sources: list[ContentSourceEvidence]
    invocations: list[ToolInvocation] = Field(default_factory=list)
    materialized: list[MaterializedAsset] = Field(default_factory=list)
    failures: list[MaterializationFailure] = Field(default_factory=list)
    filesystem_actions: list[FilesystemAction] = Field(default_factory=list)
    media_actions: list[MediaAction] = Field(default_factory=list)
    corruption_actions: list[CorruptionAction] = Field(default_factory=list)
    oracle_hash_actions: list[OracleHashAction] = Field(default_factory=list)
    network_lag_actions: list[NetworkLagAction] = Field(default_factory=list)
    network_fs_chaos_actions: list[NetworkFsChaosAction] = Field(default_factory=list)
    requested_duration_ns: int | None = None
    actual_duration_ns: int | None = None
    speed_multiplier: str | None = None
    overran_duration: bool = False
    execution_mode: MaterializationExecutionMode = MaterializationExecutionMode.MATERIALIZE
