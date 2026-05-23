"""Shared profile and corruption metadata contract models."""

from __future__ import annotations

import enum

from pydantic import BaseModel, ConfigDict


class ProfileName(enum.StrEnum):
    MALFORMED_MEDIA = "malformed-media"
    PERFORMANCE_SMOKE = "performance-smoke"
    PERFORMANCE_SCALE = "performance-scale"
    PERFORMANCE_STRESS = "performance-stress"
    NETWORK_FS_LAG = "network-fs-lag"


class CorruptionProbeOutcome(enum.StrEnum):
    FAILED_EXPECTED = "failed_expected"
    STILL_PROBEABLE = "still_probeable"


class CorruptionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: ProfileName
    event_id: str
    corruptor: str
    byte_start: int
    byte_count: int
    seed_material: str
