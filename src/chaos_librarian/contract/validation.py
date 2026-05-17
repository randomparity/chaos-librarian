"""Validation report schema (output of ``chaos-librarian validate``)."""

from __future__ import annotations

import enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ValidationSeverity(enum.StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class ValidationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    severity: ValidationSeverity
    code: str
    message: str
    line: int | None = None
    column: int | None = None
    path: str | None = None  # JSONPath-style location in scenario


class ValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    scenario_id: str
    ok: bool
    issues: list[ValidationIssue] = Field(default_factory=list)
