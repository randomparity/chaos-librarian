"""Materialization report schema."""

from __future__ import annotations

import enum
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class MaterializationStatus(enum.StrEnum):
    OK = "ok"
    TOOL_MISSING = "tool_missing"
    TOOL_FAILED = "tool_failed"
    CONTAINMENT_VIOLATION = "containment_violation"


class ToolInvocation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: str
    version: str
    command: list[str]
    exit_code: int
    duration_ns: int


class MaterializationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    run_id: uuid.UUID
    status: MaterializationStatus
    toolchain: dict[str, str]
    invocations: list[ToolInvocation] = Field(default_factory=list)
