"""Lane configuration and coverage helpers for deterministic fuzz generation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, cast

from chaos_librarian.contract.profiles import FuzzLaneName, FuzzProfileName, ProfileName
from chaos_librarian.contract.scenario import TimelineActionName


@dataclass(frozen=True, slots=True)
class LaneConfig:
    profile: FuzzProfileName
    lane: FuzzLaneName
    profiles: tuple[ProfileName, ...]
    works: int
    timeline_events: int
    required_cells: frozenset[str]


@dataclass(frozen=True, slots=True)
class CoverageReport:
    cells: frozenset[str]

    def missing_required_cells(self, required: frozenset[str]) -> frozenset[str]:
        return required - self.cells


CELL_ACTION_PREFIX: Final = "action:"
CELL_SIDE_SUBTITLE: Final = "sidecar:subtitle"
CELL_SIDE_NFO_OR_POSTER: Final = "sidecar:nfo-or-poster"
CELL_LAG_EFFECT_PREFIX: Final = "network-lag:"


LANE_CONFIGS: Final[dict[tuple[FuzzProfileName, FuzzLaneName], LaneConfig]] = {
    (FuzzProfileName.FUZZ_SMOKE, FuzzLaneName.SMOKE): LaneConfig(
        profile=FuzzProfileName.FUZZ_SMOKE,
        lane=FuzzLaneName.SMOKE,
        profiles=(ProfileName.FUZZ_SMOKE,),
        works=3,
        timeline_events=12,
        required_cells=frozenset(
            {
                "action:move_asset",
                "action:rename_file",
                "action:edit_metadata",
                "action:create_sidecar",
                "action:update_sidecar",
            }
        ),
    ),
    (FuzzProfileName.FUZZ_REGRESSION, FuzzLaneName.CORE_FS): LaneConfig(
        profile=FuzzProfileName.FUZZ_REGRESSION,
        lane=FuzzLaneName.CORE_FS,
        profiles=(ProfileName.FUZZ_REGRESSION,),
        works=10,
        timeline_events=32,
        required_cells=frozenset(
            {
                "action:move_asset",
                "action:rename_file",
                "action:delete_file",
                "action:add_file",
                "action:archive_file",
                "action:move_between_roots",
                "action:slow_copy_start",
                "action:slow_copy_commit",
            }
        ),
    ),
    (FuzzProfileName.FUZZ_REGRESSION, FuzzLaneName.MEDIA_REWRITE): LaneConfig(
        profile=FuzzProfileName.FUZZ_REGRESSION,
        lane=FuzzLaneName.MEDIA_REWRITE,
        profiles=(ProfileName.FUZZ_REGRESSION,),
        works=10,
        timeline_events=32,
        required_cells=frozenset(
            {
                "action:reencode_video",
                "action:reencode_audio",
                "action:remux_container",
                "action:edit_metadata",
            }
        ),
    ),
    (FuzzProfileName.FUZZ_REGRESSION, FuzzLaneName.SIDECAR_SUBTITLE): LaneConfig(
        profile=FuzzProfileName.FUZZ_REGRESSION,
        lane=FuzzLaneName.SIDECAR_SUBTITLE,
        profiles=(ProfileName.FUZZ_REGRESSION,),
        works=10,
        timeline_events=32,
        required_cells=frozenset(
            {
                "action:create_sidecar",
                "action:update_sidecar",
                "action:remove_sidecar",
                "action:extract_subtitle",
                "action:embed_subtitle",
                "sidecar:subtitle",
                "sidecar:nfo-or-poster",
            }
        ),
    ),
    (FuzzProfileName.FUZZ_REGRESSION, FuzzLaneName.MALFORMED): LaneConfig(
        profile=FuzzProfileName.FUZZ_REGRESSION,
        lane=FuzzLaneName.MALFORMED,
        profiles=(ProfileName.FUZZ_REGRESSION, ProfileName.MALFORMED_MEDIA),
        works=10,
        timeline_events=24,
        required_cells=frozenset(
            {
                "action:corrupt_container_header",
                "action:truncate_file",
                "action:corrupt_packet_range",
                "action:write_invalid_duration_metadata",
            }
        ),
    ),
    (FuzzProfileName.FUZZ_REGRESSION, FuzzLaneName.NEGATIVE_ORACLE): LaneConfig(
        profile=FuzzProfileName.FUZZ_REGRESSION,
        lane=FuzzLaneName.NEGATIVE_ORACLE,
        profiles=(ProfileName.FUZZ_REGRESSION, ProfileName.NEGATIVE_ORACLE),
        works=8,
        timeline_events=16,
        required_cells=frozenset({"action:wrong_oracle_hash"}),
    ),
    (FuzzProfileName.FUZZ_REGRESSION, FuzzLaneName.FILESYSTEM_ARTIFACT): LaneConfig(
        profile=FuzzProfileName.FUZZ_REGRESSION,
        lane=FuzzLaneName.FILESYSTEM_ARTIFACT,
        profiles=(ProfileName.FUZZ_REGRESSION, ProfileName.FILESYSTEM_ARTIFACTS),
        works=8,
        timeline_events=16,
        required_cells=frozenset({"action:touch_mtime"}),
    ),
    (FuzzProfileName.FUZZ_REGRESSION, FuzzLaneName.NETWORK_LAG): LaneConfig(
        profile=FuzzProfileName.FUZZ_REGRESSION,
        lane=FuzzLaneName.NETWORK_LAG,
        profiles=(ProfileName.FUZZ_REGRESSION, ProfileName.NETWORK_FS_LAG),
        works=8,
        timeline_events=18,
        required_cells=frozenset(
            {
                "action:network_lag_start",
                "action:network_lag_commit",
                "network-lag:delayed_visibility",
                "network-lag:delayed_rename",
                "network-lag:held_handle",
            }
        ),
    ),
}


def lane_config_for(profile: FuzzProfileName, lane: FuzzLaneName) -> LaneConfig:
    config = LANE_CONFIGS.get((profile, lane))
    if config is None:
        raise ValueError(f"lane {lane.value} is not valid for {profile.value}")
    return config


def profiles_for_lane(
    *,
    profile: FuzzProfileName,
    lane: FuzzLaneName,
) -> tuple[ProfileName, ...]:
    return lane_config_for(profile=profile, lane=lane).profiles


def coverage_for_payload(payload: Mapping[str, object]) -> CoverageReport:
    cells: set[str] = set()
    for event in _timeline_events(payload):
        action = event.get("action")
        if isinstance(action, str):
            cells.add(f"{CELL_ACTION_PREFIX}{action}")
        kind = event.get("kind")
        if action == TimelineActionName.CREATE_SIDECAR.value and isinstance(kind, str):
            if kind == "subtitle":
                cells.add(CELL_SIDE_SUBTITLE)
            elif kind in {"nfo", "poster"}:
                cells.add(CELL_SIDE_NFO_OR_POSTER)
        effect = event.get("effect")
        if action == TimelineActionName.NETWORK_LAG_START.value and isinstance(effect, str):
            cells.add(f"{CELL_LAG_EFFECT_PREFIX}{effect}")
    return CoverageReport(cells=frozenset(cells))


def _timeline_events(payload: Mapping[str, object]) -> tuple[Mapping[str, object], ...]:
    raw = payload.get("timeline", [])
    if not isinstance(raw, list):
        return ()
    events: list[Mapping[str, object]] = []
    for event in raw:
        if isinstance(event, dict):
            events.append(cast(Mapping[str, object], event))
    return tuple(events)
