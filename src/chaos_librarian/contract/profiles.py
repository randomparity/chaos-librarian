"""Shared profile and corruption metadata contract models."""

from __future__ import annotations

import enum

from pydantic import BaseModel, ConfigDict, Field


class ProfileName(enum.StrEnum):
    MALFORMED_MEDIA = "malformed-media"
    PERFORMANCE_SMOKE = "performance-smoke"
    PERFORMANCE_SCALE = "performance-scale"
    PERFORMANCE_STRESS = "performance-stress"
    NETWORK_FS_LAG = "network-fs-lag"
    FILESYSTEM_ARTIFACTS = "filesystem-artifacts"
    NEGATIVE_ORACLE = "negative-oracle"
    FUZZ_SMOKE = "fuzz-smoke"
    FUZZ_REGRESSION = "fuzz-regression"


class FuzzProfileName(enum.StrEnum):
    FUZZ_SMOKE = "fuzz-smoke"
    FUZZ_REGRESSION = "fuzz-regression"


class CorruptionProbeOutcome(enum.StrEnum):
    FAILED_EXPECTED = "failed_expected"
    STILL_PROBEABLE = "still_probeable"


class CorruptionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: ProfileName
    event_id: str
    corruptor: str
    byte_start: int | None = None
    byte_count: int | None = None
    seed_material: str | None = None
    stream: str | None = None
    packet_start: int | None = None
    packet_count: int | None = None
    metadata: dict[str, str | int | float | bool] = Field(default_factory=dict)
