"""Shared profile and corruption metadata contract models."""

from __future__ import annotations

import enum
from typing import Final

from pydantic import BaseModel, ConfigDict, Field


class ProfileName(enum.StrEnum):
    MALFORMED_MEDIA = "malformed-media"
    PERFORMANCE_SMOKE = "performance-smoke"
    PERFORMANCE_SCALE = "performance-scale"
    PERFORMANCE_STRESS = "performance-stress"
    NETWORK_FS_LAG = "network-fs-lag"
    NETWORK_FS_CHAOS = "network-fs-chaos"
    FILESYSTEM_ARTIFACTS = "filesystem-artifacts"
    NEGATIVE_ORACLE = "negative-oracle"
    FUZZ_SMOKE = "fuzz-smoke"
    FUZZ_REGRESSION = "fuzz-regression"


class FuzzProfileName(enum.StrEnum):
    FUZZ_SMOKE = "fuzz-smoke"
    FUZZ_REGRESSION = "fuzz-regression"


class FuzzLaneName(enum.StrEnum):
    SMOKE = "smoke"
    CORE_FS = "core-fs"
    MEDIA_REWRITE = "media-rewrite"
    SIDECAR_SUBTITLE = "sidecar-subtitle"
    MALFORMED = "malformed"
    NEGATIVE_ORACLE = "negative-oracle"
    FILESYSTEM_ARTIFACT = "filesystem-artifact"
    NETWORK_LAG = "network-lag"
    NETWORK_FS_CHAOS = "network-fs-chaos"
    TV_TOPOLOGY = "tv-topology"
    MUSIC_TOPOLOGY = "music-topology"


FUZZ_LANES_BY_PROFILE: Final[dict[FuzzProfileName, frozenset[FuzzLaneName]]] = {
    FuzzProfileName.FUZZ_SMOKE: frozenset({FuzzLaneName.SMOKE}),
    FuzzProfileName.FUZZ_REGRESSION: frozenset(
        {
            FuzzLaneName.CORE_FS,
            FuzzLaneName.MEDIA_REWRITE,
            FuzzLaneName.SIDECAR_SUBTITLE,
            FuzzLaneName.MALFORMED,
            FuzzLaneName.NEGATIVE_ORACLE,
            FuzzLaneName.FILESYSTEM_ARTIFACT,
            FuzzLaneName.NETWORK_LAG,
            FuzzLaneName.NETWORK_FS_CHAOS,
            FuzzLaneName.TV_TOPOLOGY,
            FuzzLaneName.MUSIC_TOPOLOGY,
        }
    ),
}


CANONICAL_FUZZ_LANES: Final[dict[FuzzProfileName, tuple[FuzzLaneName, ...]]] = {
    FuzzProfileName.FUZZ_SMOKE: (FuzzLaneName.SMOKE,),
    FuzzProfileName.FUZZ_REGRESSION: (
        FuzzLaneName.CORE_FS,
        FuzzLaneName.MEDIA_REWRITE,
        FuzzLaneName.SIDECAR_SUBTITLE,
        FuzzLaneName.MALFORMED,
        FuzzLaneName.NEGATIVE_ORACLE,
        FuzzLaneName.FILESYSTEM_ARTIFACT,
        FuzzLaneName.NETWORK_LAG,
        FuzzLaneName.NETWORK_FS_CHAOS,
        FuzzLaneName.TV_TOPOLOGY,
        FuzzLaneName.MUSIC_TOPOLOGY,
    ),
}


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
