"""Materialization report schema (v2).

Carries started_at/finished_at, platform, structured ToolchainInfo,
per-asset MaterializedAsset records, per-failure MaterializationFailure
records, and an Outcome enum that includes an explicit ``success`` signal.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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

    asset_id: str | None
    stage: str
    exit_code: int | None
    stderr_tail: str
    invocation_index: int | None


class MaterializationReport(BaseModel):
    """Top-level ``materialization.json`` body."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[2]
    run_id: uuid.UUID
    outcome: Outcome
    platform: str
    started_at: datetime
    finished_at: datetime
    toolchain: ToolchainInfo
    invocations: list[ToolInvocation] = Field(default_factory=list)
    materialized: list[MaterializedAsset] = Field(default_factory=list)
    failures: list[MaterializationFailure] = Field(default_factory=list)
