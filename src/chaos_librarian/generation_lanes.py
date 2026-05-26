"""Lane configuration and coverage helpers for deterministic fuzz generation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, cast

from chaos_librarian.contract.profiles import FuzzLaneName, FuzzProfileName, ProfileName
from chaos_librarian.contract.scenario import SidecarKind, TimelineActionName


@dataclass(frozen=True, slots=True)
class LaneConfig:
    profile: FuzzProfileName
    lane: FuzzLaneName
    profiles: tuple[ProfileName, ...]
    movies: int
    series: int
    artists: int
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


def _action_cell(action: TimelineActionName) -> str:
    return f"{CELL_ACTION_PREFIX}{action.value}"


LANE_CONFIGS: Final[dict[tuple[FuzzProfileName, FuzzLaneName], LaneConfig]] = {
    (FuzzProfileName.FUZZ_SMOKE, FuzzLaneName.SMOKE): LaneConfig(
        profile=FuzzProfileName.FUZZ_SMOKE,
        lane=FuzzLaneName.SMOKE,
        profiles=(ProfileName.FUZZ_SMOKE,),
        movies=3,
        series=0,
        artists=0,
        timeline_events=12,
        required_cells=frozenset(
            {
                _action_cell(TimelineActionName.MOVE_ASSET),
                _action_cell(TimelineActionName.RENAME_FILE),
                _action_cell(TimelineActionName.EDIT_METADATA),
                _action_cell(TimelineActionName.CREATE_SIDECAR),
                _action_cell(TimelineActionName.UPDATE_SIDECAR),
            }
        ),
    ),
    (FuzzProfileName.FUZZ_REGRESSION, FuzzLaneName.CORE_FS): LaneConfig(
        profile=FuzzProfileName.FUZZ_REGRESSION,
        lane=FuzzLaneName.CORE_FS,
        profiles=(ProfileName.FUZZ_REGRESSION,),
        movies=10,
        series=0,
        artists=0,
        timeline_events=32,
        required_cells=frozenset(
            {
                _action_cell(TimelineActionName.MOVE_ASSET),
                _action_cell(TimelineActionName.RENAME_FILE),
                _action_cell(TimelineActionName.DELETE_FILE),
                _action_cell(TimelineActionName.ADD_FILE),
                _action_cell(TimelineActionName.ARCHIVE_FILE),
                _action_cell(TimelineActionName.MOVE_BETWEEN_ROOTS),
                _action_cell(TimelineActionName.SLOW_COPY_START),
                _action_cell(TimelineActionName.SLOW_COPY_COMMIT),
            }
        ),
    ),
    (FuzzProfileName.FUZZ_REGRESSION, FuzzLaneName.MEDIA_REWRITE): LaneConfig(
        profile=FuzzProfileName.FUZZ_REGRESSION,
        lane=FuzzLaneName.MEDIA_REWRITE,
        profiles=(ProfileName.FUZZ_REGRESSION,),
        movies=10,
        series=0,
        artists=0,
        timeline_events=32,
        required_cells=frozenset(
            {
                _action_cell(TimelineActionName.REENCODE_VIDEO),
                _action_cell(TimelineActionName.REENCODE_AUDIO),
                _action_cell(TimelineActionName.REMUX_CONTAINER),
                _action_cell(TimelineActionName.EDIT_METADATA),
            }
        ),
    ),
    (FuzzProfileName.FUZZ_REGRESSION, FuzzLaneName.SIDECAR_SUBTITLE): LaneConfig(
        profile=FuzzProfileName.FUZZ_REGRESSION,
        lane=FuzzLaneName.SIDECAR_SUBTITLE,
        profiles=(ProfileName.FUZZ_REGRESSION,),
        movies=10,
        series=0,
        artists=0,
        timeline_events=32,
        required_cells=frozenset(
            {
                _action_cell(TimelineActionName.CREATE_SIDECAR),
                _action_cell(TimelineActionName.UPDATE_SIDECAR),
                _action_cell(TimelineActionName.REMOVE_SIDECAR),
                _action_cell(TimelineActionName.EXTRACT_SUBTITLE),
                _action_cell(TimelineActionName.EMBED_SUBTITLE),
                "sidecar:subtitle",
                "sidecar:nfo-or-poster",
            }
        ),
    ),
    (FuzzProfileName.FUZZ_REGRESSION, FuzzLaneName.MALFORMED): LaneConfig(
        profile=FuzzProfileName.FUZZ_REGRESSION,
        lane=FuzzLaneName.MALFORMED,
        profiles=(ProfileName.FUZZ_REGRESSION, ProfileName.MALFORMED_MEDIA),
        movies=10,
        series=0,
        artists=0,
        timeline_events=24,
        required_cells=frozenset(
            {
                _action_cell(TimelineActionName.CORRUPT_CONTAINER_HEADER),
                _action_cell(TimelineActionName.TRUNCATE_FILE),
                _action_cell(TimelineActionName.CORRUPT_PACKET_RANGE),
                _action_cell(TimelineActionName.WRITE_INVALID_DURATION_METADATA),
            }
        ),
    ),
    (FuzzProfileName.FUZZ_REGRESSION, FuzzLaneName.NEGATIVE_ORACLE): LaneConfig(
        profile=FuzzProfileName.FUZZ_REGRESSION,
        lane=FuzzLaneName.NEGATIVE_ORACLE,
        profiles=(ProfileName.FUZZ_REGRESSION, ProfileName.NEGATIVE_ORACLE),
        movies=8,
        series=0,
        artists=0,
        timeline_events=16,
        required_cells=frozenset({_action_cell(TimelineActionName.WRONG_ORACLE_HASH)}),
    ),
    (FuzzProfileName.FUZZ_REGRESSION, FuzzLaneName.FILESYSTEM_ARTIFACT): LaneConfig(
        profile=FuzzProfileName.FUZZ_REGRESSION,
        lane=FuzzLaneName.FILESYSTEM_ARTIFACT,
        profiles=(ProfileName.FUZZ_REGRESSION, ProfileName.FILESYSTEM_ARTIFACTS),
        movies=8,
        series=0,
        artists=0,
        timeline_events=16,
        required_cells=frozenset({_action_cell(TimelineActionName.TOUCH_MTIME)}),
    ),
    (FuzzProfileName.FUZZ_REGRESSION, FuzzLaneName.NETWORK_LAG): LaneConfig(
        profile=FuzzProfileName.FUZZ_REGRESSION,
        lane=FuzzLaneName.NETWORK_LAG,
        profiles=(ProfileName.FUZZ_REGRESSION, ProfileName.NETWORK_FS_LAG),
        movies=8,
        series=0,
        artists=0,
        timeline_events=18,
        required_cells=frozenset(
            {
                _action_cell(TimelineActionName.NETWORK_LAG_START),
                _action_cell(TimelineActionName.NETWORK_LAG_COMMIT),
                "network-lag:delayed_visibility",
                "network-lag:delayed_rename",
                "network-lag:held_handle",
            }
        ),
    ),
    (FuzzProfileName.FUZZ_REGRESSION, FuzzLaneName.TV_TOPOLOGY): LaneConfig(
        profile=FuzzProfileName.FUZZ_REGRESSION,
        lane=FuzzLaneName.TV_TOPOLOGY,
        profiles=(ProfileName.FUZZ_REGRESSION,),
        movies=0,
        series=1,
        artists=0,
        timeline_events=18,
        required_cells=frozenset(
            {
                _action_cell(TimelineActionName.RENUMBER_EPISODE),
                _action_cell(TimelineActionName.MOVE_EPISODE_TO_SEASON),
                _action_cell(TimelineActionName.RENAME_FILE),
                _action_cell(TimelineActionName.REENCODE_VIDEO),
            }
        ),
    ),
    (FuzzProfileName.FUZZ_REGRESSION, FuzzLaneName.MUSIC_TOPOLOGY): LaneConfig(
        profile=FuzzProfileName.FUZZ_REGRESSION,
        lane=FuzzLaneName.MUSIC_TOPOLOGY,
        profiles=(ProfileName.FUZZ_REGRESSION,),
        movies=0,
        series=0,
        artists=1,
        timeline_events=18,
        required_cells=frozenset(
            {
                _action_cell(TimelineActionName.RENUMBER_DISC),
                _action_cell(TimelineActionName.MOVE_TRACK_TO_DISC),
                _action_cell(TimelineActionName.RENAME_FILE),
                _action_cell(TimelineActionName.REENCODE_AUDIO),
            }
        ),
    ),
}


def lane_config_for(profile: FuzzProfileName, lane: FuzzLaneName) -> LaneConfig:
    config = LANE_CONFIGS.get((profile, lane))
    if config is None:
        raise ValueError(f"lane {lane.value} is not valid for {profile.value}")
    return config


def coverage_for_payload(payload: Mapping[str, object]) -> CoverageReport:
    cells: set[str] = set()
    raw = payload.get("timeline", [])
    if not isinstance(raw, list):
        return CoverageReport(cells=frozenset())
    for event in raw:
        if not isinstance(event, dict):
            continue
        event = cast(Mapping[str, object], event)
        action = event.get("action")
        if isinstance(action, str):
            cells.add(f"{CELL_ACTION_PREFIX}{action}")
        kind = event.get("kind")
        if action == TimelineActionName.CREATE_SIDECAR.value and isinstance(kind, str):
            if kind == SidecarKind.SUBTITLE.value:
                cells.add(CELL_SIDE_SUBTITLE)
            elif kind in {SidecarKind.NFO.value, SidecarKind.POSTER.value}:
                cells.add(CELL_SIDE_NFO_OR_POSTER)
        effect = event.get("effect")
        if action == TimelineActionName.NETWORK_LAG_START.value and isinstance(effect, str):
            cells.add(f"{CELL_LAG_EFFECT_PREFIX}{effect}")
    return CoverageReport(cells=frozenset(cells))
