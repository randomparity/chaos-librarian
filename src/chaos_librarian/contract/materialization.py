"""Materialization report schema (v5).

Carries started_at/finished_at, platform, structured ToolchainInfo,
per-asset MaterializedAsset records, per-failure MaterializationFailure
records, per-phase-B FilesystemAction and MediaAction audit records, and
an Outcome enum that includes an explicit ``success`` signal.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from chaos_librarian.contract.scenario import TimelineActionName


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


class FailureStage(enum.StrEnum):
    """Subprocess stage that produced a MaterializationFailure."""

    FFMPEG = "ffmpeg"
    FFPROBE = "ffprobe"
    FILESYSTEM = "filesystem"
    MEDIA = "media"


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
    input_content_hash: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    output_content_hash: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    tool_invocation_index: int | None = None
    duration_ns: int


class MaterializationReport(BaseModel):
    """Top-level ``materialization.json`` body."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[5]
    run_id: uuid.UUID
    outcome: Outcome
    platform: str
    started_at: datetime
    finished_at: datetime
    toolchain: ToolchainInfo
    invocations: list[ToolInvocation] = Field(default_factory=list)
    materialized: list[MaterializedAsset] = Field(default_factory=list)
    failures: list[MaterializationFailure] = Field(default_factory=list)
    filesystem_actions: list[FilesystemAction] = Field(default_factory=list)
    media_actions: list[MediaAction] = Field(default_factory=list)
    requested_duration_ns: int | None = None
    actual_duration_ns: int | None = None
    speed_multiplier: str | None = None
    overran_duration: bool = False
    execution_mode: MaterializationExecutionMode = MaterializationExecutionMode.MATERIALIZE
