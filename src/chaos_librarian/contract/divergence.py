"""Divergence report contract emitted by adapter comparisons."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CompareMode(enum.StrEnum):
    """Comparison depth requested by the adapter or CLI."""

    FINAL_STATE = "final-state"
    IDENTITY_HISTORY = "identity-history"


class DivergenceCode(enum.StrEnum):
    """Initial Sprint 9 divergence finding codes."""

    ASSET_MISSING = "D_ASSET_MISSING"
    ASSET_UNEXPECTED = "D_ASSET_UNEXPECTED"
    MATCH_AMBIGUOUS = "D_MATCH_AMBIGUOUS"
    PATH_MISMATCH = "D_PATH_MISMATCH"
    DELETION_MISMATCH = "D_DELETION_MISMATCH"
    HASH_MISMATCH = "D_HASH_MISMATCH"
    PROBE_MISMATCH = "D_PROBE_MISMATCH"
    SIDECAR_MISSING = "D_SIDECAR_MISSING"
    SIDECAR_UNEXPECTED = "D_SIDECAR_UNEXPECTED"
    TOPOLOGY_MISMATCH = "D_TOPOLOGY_MISMATCH"
    IDENTITY_SPLIT = "D_IDENTITY_SPLIT"
    HISTORY_CONFLICT = "D_HISTORY_CONFLICT"
    HISTORY_MISSING = "D_HISTORY_MISSING"
    HISTORY_UNEXPECTED = "D_HISTORY_UNEXPECTED"


class DivergenceSeverity(enum.StrEnum):
    """Severity for a divergence finding."""

    ERROR = "error"
    WARNING = "warning"


class MatchEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["current_path", "historical_path", "content_hash", "topology"]
    value: str
    oracle_asset_id: str | None = None
    observed_ref: str | None = None


class DivergenceFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: DivergenceCode
    severity: DivergenceSeverity
    message: str
    oracle_asset_id: str | None = None
    oracle_event_id: str | None = None
    related_oracle_event_ids: list[str] = Field(default_factory=list)
    observed_ref: str | None = None
    expected: object | None = None
    observed: object | None = None
    evidence: list[MatchEvidence] = Field(default_factory=list)


class DivergenceFixtureMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_dir: str
    execution_mode: str
    asset_count: int
    journal_entries: int


class DivergenceObservedMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    consumer_name: str
    consumer_version: str | None = None
    observed_at: datetime
    asset_count: int


class DivergenceReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    run_id: uuid.UUID
    mode: CompareMode
    ok: bool
    fixture: DivergenceFixtureMetadata
    observed: DivergenceObservedMetadata
    findings: list[DivergenceFinding] = Field(default_factory=list)

    @model_validator(mode="after")
    def ok_matches_error_findings(self) -> DivergenceReport:
        has_error = any(finding.severity is DivergenceSeverity.ERROR for finding in self.findings)
        if self.ok == has_error:
            raise ValueError("ok must be false when error findings are present")
        return self
