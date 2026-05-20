"""Materialization report schema (v3).

Carries started_at/finished_at, platform, structured ToolchainInfo,
per-asset MaterializedAsset records, per-failure MaterializationFailure
records, per-phase-B FilesystemAction audit records, and an Outcome enum
that includes an explicit ``success`` signal.
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


class FailureStage(enum.StrEnum):
    """Subprocess stage that produced a MaterializationFailure."""

    FFMPEG = "ffmpeg"
    FFPROBE = "ffprobe"
    FILESYSTEM = "filesystem"


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


class MaterializationReport(BaseModel):
    """Top-level ``materialization.json`` body."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[3]
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
